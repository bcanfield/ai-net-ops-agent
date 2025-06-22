import os
from dotenv import load_dotenv

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import asyncio

from astream_events_handler import invoke_our_graph   # Utility function to handle events from astream_events from graph

load_dotenv()

# System-level instructions to drive tool chaining
SYSTEM_PROMPT = (
    "You are a network-operations assistant with a full toolbox: interface discovery, stats, pings, "
    "port scanning, DNS, traceroute, MAC lookup, public-IP, plus general web search. "
    "When a user asks a broad network-troubleshooting question, proactively select and chain the "
    "relevant tools in the logical order needed to diagnose or inventory their network. "
    "Explain your plan, execute the tools, then summarize the results. "
    "Do not use placeholder values like [key service IP] or [hostname]; always extract actual values from the user query or ask for clarification if missing. "
    "If the user refers to abstract terms (e.g., 'key services', 'our servers') and you cannot resolve them to real hostnames or IPs, ask the user to specify the exact targets before running any tools."
)

st.title("AI Net Ops Agent")
st.markdown("#### AI agent showcasing network operations and troubleshooting")

# Showcase example questions for net-admin use cases
showcase_questions = [
    # Full diagnostic drive a full tool chain
    "Run a comprehensive network diagnostic: list all interfaces with their IPs and MACs, get stats for each interface.",
    # Ambiguous prompt to demonstrate follow-up clarification
    "I’m seeing high latency to our key services—investigate and summarize what you find.",
    # Specific web server troubleshooting
    "I can’t reach my web server. Figure out why and suggest next steps.",
    # Audit connectivity to multiple targets including private gateway
    "Audit connectivity to my multiple web servers",
]


# Initialize the expander state
if "expander_open" not in st.session_state:
    st.session_state.expander_open = True

# Check if the OpenAI API key is set
if not os.getenv('OPENAI_API_KEY'):
    # If not, display a sidebar input for the user to provide the API key
    st.sidebar.header("OPENAI_API_KEY Setup")
    api_key = st.sidebar.text_input(label="API Key", type="password", label_visibility="collapsed")
    os.environ["OPENAI_API_KEY"] = api_key
    # If no key is provided, show an info message and stop further execution and wait till key is entered
    if not api_key:
        st.info("Please enter your OPENAI_API_KEY in the sidebar.")
        st.stop()

# Capture user input from chat input
prompt = st.chat_input()

# Toggle expander state based on user input
if prompt is not None:
    st.session_state.expander_open = False  # Close the expander when the user starts typing

# st write magic
with st.expander(label="Example Prompts to Try Out", expanded=st.session_state.expander_open):
    """
    Here are some example prompts you can try with the AI Net Ops Agent:
    """
    for q in showcase_questions:
        st.markdown(f"- **{q}**")

# Initialize chat messages in session state
if "messages" not in st.session_state:
    # prepend system prompt for autonomous tool chaining
    st.session_state["messages"] = [SystemMessage(content=SYSTEM_PROMPT), AIMessage(content="How can I help you?")]

# Loop through all messages in the session state and render them as a chat on every st.refresh mech
for msg in st.session_state.messages:
    # https://docs.streamlit.io/develop/api-reference/chat/st.chat_message
    # we store them as AIMessage and HumanMessage as its easier to send to LangGraph
    if isinstance(msg, AIMessage):
        st.chat_message("assistant").write(msg.content)
    elif isinstance(msg, HumanMessage):
        st.chat_message("user").write(msg.content)

# Handle user input if provided
if prompt:
    st.session_state.messages.append(HumanMessage(content=prompt))
    st.chat_message("user").write(prompt)

    with st.chat_message("assistant"):
        # create a placeholder container for streaming and any other events to visually render here
        placeholder = st.container()
        response = asyncio.run(invoke_our_graph(st.session_state.messages, placeholder))
        st.session_state.messages.append(AIMessage(response))
