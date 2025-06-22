from typing import Annotated, TypedDict, Literal

from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool, StructuredTool
from langgraph.graph import START, StateGraph
from langgraph.graph.message import AnyMessage, add_messages
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from langchain_openai import ChatOpenAI
import netifaces
import psutil
import subprocess
import socket
import requests

# Define a search tool using DuckDuckGo API wrapper
search_DDG = StructuredTool.from_function(
        name="Search",
        func=DuckDuckGoSearchAPIWrapper().run,  # Executes DuckDuckGo search using the provided query
        description=f"""
        useful for when you need to answer questions about current events. You should ask targeted questions
        """,
    )

@tool
def list_network_devices():
    """List all interfaces with IP and MAC."""
    result = {}
    for intf in netifaces.interfaces():
        addrs = netifaces.ifaddresses(intf)
        ip4 = addrs.get(netifaces.AF_INET, [{}])[0].get("addr")
        mac = addrs.get(netifaces.AF_LINK, [{}])[0].get("addr")
        result[intf] = {"ip": ip4, "mac": mac}
    return result

@tool
def get_device_details(interface: str):
    """Details (stats, addrs) for a single interface."""
    try:
        addrs = netifaces.ifaddresses(interface)
        stats = psutil.net_if_stats().get(interface)
    except KeyError:
        return f"Interface '{interface}' not found."
    return {
        "addresses": addrs,
        "is_up": stats.isup,
        "speed_mbps": stats.speed,
        "mtu": stats.mtu,
    }

@tool
def ping_host(host: str, count: int = 4):
    """ICMP ping via system ping utility."""
    proc = subprocess.run(
        ["ping", "-c", str(count), host],
        capture_output=True, text=True
    )
    return proc.stdout or proc.stderr

@tool
def port_scan(host: str, ports: str = "1-1024"):
    """Simple TCP port scan. ports can be comma-sep or range 'start-end'."""
    open_ports = []
    if "-" in ports:
        start, end = map(int, ports.split("-", 1))
        port_range = range(start, end + 1)
    else:
        port_range = [int(p) for p in ports.split(",")]
    for p in port_range:
        try:
            with socket.create_connection((host, p), timeout=0.5):
                open_ports.append(p)
        except Exception:
            pass
    return {"host": host, "open_ports": open_ports}

@tool
def resolve_dns(hostname: str):
    """DNS lookup."""
    try:
        name, aliases, addrs = socket.gethostbyname_ex(hostname)
        return {"name": name, "aliases": aliases, "addresses": addrs}
    except Exception as e:
        return str(e)

@tool
def traceroute_host(host: str, max_hops: int = 30):
    """Traceroute via system utility."""
    proc = subprocess.run(
        ["traceroute", "-m", str(max_hops), host],
        capture_output=True, text=True
    )
    return proc.stdout or proc.stderr

@tool
def lookup_mac_vendor(mac: str):
    """Lookup vendor for a MAC address via public API."""
    try:
        resp = requests.get(f"https://api.macvendors.com/{mac}", timeout=2)
        return resp.text
    except Exception as e:
        return str(e)

@tool
def get_public_ip():
    """Fetch the public IP address of this machine."""
    try:
        resp = requests.get("https://api.ipify.org?format=json", timeout=2)
        data = resp.json()
        return data.get("ip")
    except Exception as e:
        return str(e)

# List of tools that will be accessible to the graph via the ToolNode
tools = [
    list_network_devices,
    get_device_details,
    ping_host,
    port_scan,
    resolve_dns,
    traceroute_host,
    lookup_mac_vendor,
    get_public_ip,
    search_DDG,
]
tool_node = ToolNode(tools)

# This is the default state same as "MessageState" TypedDict but allows us accessibility to custom keys
class GraphsState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    # Custom keys for additional data can be added here such as - conversation_id: str

graph = StateGraph(GraphsState)

# Function to decide whether to continue tool usage or end the process
def should_continue(state: GraphsState) -> Literal["tools", "__end__"]:
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:  # Check if the last message has any tool calls
        return "tools"  # Continue to tool execution
    return "__end__"  # End the conversation if no tool is needed

# Core invocation of the model
def _call_model(state: GraphsState):
    messages = state["messages"]
    llm = ChatOpenAI(
        temperature=0.7,
        streaming=True,
        # specifically for OpenAI we have to set parallel tool call to false
        # because of st primitively visually rendering the tool results
    ).bind_tools(tools, parallel_tool_calls=False)
    response = llm.invoke(messages)
    return {"messages": [response]}  # add the response to the messages using LangGraph reducer paradigm

# Define the structure (nodes and directional edges between nodes) of the graph
graph.add_edge(START, "modelNode")
graph.add_node("tools", tool_node)
graph.add_node("modelNode", _call_model)

# Add conditional logic to determine the next step based on the state (to continue or to end)
graph.add_conditional_edges(
    "modelNode",
    should_continue,  # This function will decide the flow of execution
)
graph.add_edge("tools", "modelNode")

# Compile the state graph into a runnable object
graph_runnable = graph.compile()