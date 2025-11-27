# -*- coding: utf-8 -*-
"""Command-line interface for Data Juicer Agent."""
import os
import sys
import argparse
import asyncio
from typing import List

from agentscope.model import DashScopeChatModel
from agentscope.formatter import DashScopeChatFormatter
from agentscope.memory import InMemoryMemory
from agentscope.agent import UserAgent

from data_juicer_agents.core import (
    create_agent,
    DJ_SYS_PROMPT,
    DJ_DEV_SYS_PROMPT,
    ROUTER_SYS_PROMPT,
    MCP_SYS_PROMPT,
    register_dj_agent_hooks,
)
from data_juicer_agents.tools import (
    dj_toolkit,
    dj_dev_toolkit,
    mcp_tools,
    get_mcp_toolkit,
    agents2toolkit,
)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Data Juicer Agent - A multi-agent data processing system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default agents (dj and dj_dev)
  dj-agents
  
  # Run with specific agents
  dj-agents --agents dj dj_dev dj_mcp
  
  # Use AgentScope Studio
  dj-agents --use-studio
  
  # Set retrieval mode
  dj-agents --retrieval-mode vector
        """
    )
    
    parser.add_argument(
        "--use-studio",
        "-u",
        action="store_true",
        help="Enable AgentScope Studio for visualization"
    )
    
    parser.add_argument(
        "--agents",
        "-a",
        nargs="+",
        default=["dj", "dj_dev"],
        choices=["dj", "dj_dev", "dj_mcp"],
        help="List of agents to enable (default: dj dj_dev)"
    )
    
    parser.add_argument(
        "--retrieval-mode",
        "-r",
        choices=["auto", "vector", "llm"],
        default="auto",
        help="Retrieval mode for operators (default: auto)"
    )
    
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version="%(prog)s 0.1.0"
    )
    
    return parser.parse_args()


async def run_agent(
    use_studio: bool = False,
    available_agents: List[str] = None,
    retrieval_mode: str = "auto",
):
    """
    Main function for running the agent.

    :param use_studio: Whether to use agentscope studio.
    :param available_agents: List of available agents. Options: dj (dj_process_agent), dj_dev (dj_dev_agent), dj_mcp (mcp_datajuicer_agent)
    :param retrieval_mode: Retrieval mode for operators. Options: auto, vector, llm
    """
    if available_agents is None:
        available_agents = ["dj", "dj_dev"]

    # Create shared configuration
    model = DashScopeChatModel(
        model_name="qwen-max",
        api_key=os.environ.get("DASHSCOPE_API_KEY"),
        stream=True,
        enable_thinking=False,
    )

    dev_model = DashScopeChatModel(
        model_name="qwen3-coder-480b-a35b-instruct",
        api_key=os.environ.get("DASHSCOPE_API_KEY"),
        stream=True,
        enable_thinking=False,
    )

    formatter = DashScopeChatFormatter()
    memory = InMemoryMemory()

    user = UserAgent("User")

    # Initialize dj_func_info at agent startup for lifecycle management
    if "dj" in available_agents or "dj_dev" in available_agents:
        print("Initializing DataJuicer operators information...")
        from data_juicer_agents.tools.op_manager.op_retrieval import init_dj_func_info
        if init_dj_func_info():
            print("✓ DataJuicer operators information initialized successfully")
        else:
            print("⚠ Warning: Failed to initialize DataJuicer operators information")

    if "dj" in available_agents:
        # Set global retrieval mode for tools to use
        os.environ["RETRIEVAL_MODE"] = retrieval_mode
        print(f"Using retrieval mode: {retrieval_mode}")

    agents = []
    for agent_name in available_agents:
        if agent_name == "dj":
            # Create agents using unified create_agent function
            dj_agent = create_agent(
                "dj_process_agent",
                DJ_SYS_PROMPT,
                dj_toolkit,
                (
                    "A professional data preprocessing AI assistant with the following core capabilities: \n"
                    "Tool Matching \n"
                    "- Query and validate suitable DataJuicer operators; \n"
                    "Configuration Generation \n"
                    "- Create YAML configuration files and preview data; \n"
                    "Task Execution - Run data processing pipelines and output results"
                ),
                model,
                formatter,
                memory,
            )
            # Register cleaning hooks for shell command outputs
            register_dj_agent_hooks(dj_agent)
            agents.append(dj_agent)

        if agent_name == "dj_dev":
            # DJ Development Agent for operator development
            dj_dev_agent = create_agent(
                "dj_dev_agent",
                DJ_DEV_SYS_PROMPT,
                dj_dev_toolkit,
                (
                    "An expert DataJuicer development assistant specializing in creating new DataJuicer operators. \n"
                    "Core capabilities: \n"
                    "Reference Retrieval - fetch base classes and examples; \n"
                    "Environment Configuration - handle DATA_JUICER_PATH setup. if user provides a DataJuicer path requiring setup/update, please call this agent;\n; "
                    "Code Generation - write complete, convention-compliant operator code"
                ),
                dev_model,
                formatter,
                memory,
            )
            agents.append(dj_dev_agent)

        if agent_name == "dj_mcp":
            mcp_toolkit, _ = await get_mcp_toolkit()
            for tool in mcp_tools:
                mcp_toolkit.register_tool_function(tool)

            mcp_agent = create_agent(
                "dj_process_mcp_agent",
                MCP_SYS_PROMPT,
                mcp_toolkit,
                (
                    "DataJuicer MCP Agent powered by Recipe Flow MCP server. \n"
                    "Core capabilities: \n"
                    "- Filter operators by tags/categories using MCP protocol; \n"
                    "- Real-time data processing pipeline execution. \n"
                ),
                model,
                formatter,
                memory,
            )
            agents.append(mcp_agent)

    from data_juicer_agents.tools.router_helpers import refresh_operators_info, query_dj_operators
    from data_juicer_agents.tools.dj_dev_helpers import configure_data_juicer_path
    
    # Create router toolkit with smart routing function
    router_toolkit = agents2toolkit(agents)
    router_toolkit.register_tool_function(query_dj_operators)
    router_toolkit.register_tool_function(refresh_operators_info)
    router_toolkit.register_tool_function(configure_data_juicer_path)
    
    # Router agent - uses agents2tools to dynamically generate tools from all agents
    router_agent = create_agent(
        "Router",
        ROUTER_SYS_PROMPT,
        router_toolkit,
        "A router agent that intelligently routes tasks to specialized DataJuicer agents",
        model,
        formatter,
        InMemoryMemory(),  # Router uses its own memory instance
    )

    if use_studio:
        import agentscope

        agentscope.init(
            studio_url="http://localhost:3000",
            project="data_agents",
        )

    msg = None
    while True:
        msg = await user(msg)
        if msg.get_text_content() == "exit":
            break
        # Router agent handles the entire task with automatic multi-step routing
        msg = await router_agent(msg)


def main():
    """Main entry point for the CLI."""
    args = parse_args()
    
    # Check for required environment variable
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("Error: DASHSCOPE_API_KEY environment variable is not set", file=sys.stderr)
        print("Please set it with: export DASHSCOPE_API_KEY=your_api_key", file=sys.stderr)
        sys.exit(1)
    
    try:
        asyncio.run(run_agent(
            use_studio=args.use_studio,
            available_agents=args.agents,
            retrieval_mode=args.retrieval_mode,
        ))
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
