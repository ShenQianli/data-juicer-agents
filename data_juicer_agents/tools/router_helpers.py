# -*- coding: utf-8 -*-
"""Router agent using implicit routing"""
import os
from typing import Callable, Dict, Optional
from agentscope.agent import AgentBase
from agentscope.message import Msg, TextBlock
from agentscope.tool import ToolResponse
from .op_manager.op_retrieval import retrieve_ops, get_dj_func_info

def _format_tool_names_to_class_entries(tool_names):
    """Convert tool names list to formatted class entries string"""
    if not tool_names:
        return ""

    tools_info = get_dj_func_info()

    # Create a mapping from class_name to tool info for quick lookup
    tools_map = {tool["class_name"]: tool for tool in tools_info}

    formatted_entries = []
    for i, tool_name in enumerate(tool_names):
        if tool_name in tools_map:
            tool_info = tools_map[tool_name]
            class_entry = (
                f"{i+1}. {tool_info['class_name']}: {tool_info['class_desc']}"
            )
            class_entry += "\n" + tool_info["arguments"]
            formatted_entries.append(class_entry)

    return "\n".join(formatted_entries)


async def query_dj_operators(query: str, limit: int = 20) -> ToolResponse:
    """Query DataJuicer operators by natural language description.

    Retrieves relevant operators from DataJuicer library based on user query.
    Supports matching by functionality, data type, and processing scenarios.

    Args:
        query (str): Natural language operator query
        limit (int): Maximum number of operators to return (default: 20)

    Returns:
        ToolResponse: Tool response containing matched operators with names, descriptions, and parameters
    """

    try:
        # Retrieve operator names using existing functionality with limit
        # Use retrieval mode from environment variable if set
        retrieval_mode = os.environ.get("RETRIEVAL_MODE", "auto")
        tool_names = await retrieve_ops(
            query,
            limit=limit,
            mode=retrieval_mode,
        )

        if not tool_names:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"No matching DataJuicer operators found for query: {query}\n"
                        f"Suggestions:\n"
                        f"1. Use more specific keywords like 'text filter', 'image processing'\n"
                        f"2. Check spelling and try alternative terms\n"
                        f"3. Try English keywords for better matching",
                    ),
                ],
            )

        # Format tool names to class entries
        retrieved_operators = _format_tool_names_to_class_entries(tool_names)

        # Format response
        result_text = f"🔍 DataJuicer Operator Query Results\n"
        result_text += f"Query: {query}\n"
        result_text += f"Limit: {limit} operators\n"
        result_text += f"{'='*50}\n\n"
        result_text += retrieved_operators

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=result_text,
                ),
            ],
        )

    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error querying DataJuicer operators: {str(e)}\n"
                    f"Please verify query parameters and retry.",
                ),
            ],
        )

def agent_to_tool(
    agent: AgentBase,
    tool_name: str = None,
    description: str = None,
) -> Callable:
    """
    Convert any agent to a tool function that can be registered in toolkit.

    Args:
        agent: The agent instance to convert
        tool_name: Optional custom tool name (defaults to agent.name)
        description: Optional tool description (defaults to agent's docstring or sys_prompt)

    Returns:
        A tool function that can be registered with toolkit.register_tool_function()
    """
    # Get tool name and description
    if tool_name is None:
        tool_name = getattr(agent, "name", "agent_tool")

    if description is None:
        # Try to get description from agent's docstring or sys_prompt
        if hasattr(agent, "__doc__") and agent.__doc__:
            description = agent.__doc__.strip()
        elif hasattr(agent, "sys_prompt"):
            description = f"Agent: {agent.sys_prompt[:100]}..."
        elif hasattr(agent, "_sys_prompt"):
            description = f"Agent: {agent._sys_prompt[:100]}..."
        else:
            description = f"Tool function for {tool_name}"

    async def tool_function(task: str) -> ToolResponse:
        # Create message and call the agent
        msg = Msg("router", task, "user")
        result = await agent(msg)

        # Extract content from the result
        if hasattr(result, "get_content_blocks"):
            content = result.get_content_blocks("text")
            return ToolResponse(
                content=content,
                metadata={
                    "agent_name": getattr(agent, "name", "unknown"),
                    "task": task,
                },
            )
        else:
            raise ValueError(f"Not a valid Msg object: {result}")

    # Set function name and docstring
    tool_function.__name__ = f"call_{tool_name.lower().replace(' ', '_')}"
    tool_function.__doc__ = f"{description}\n\nArgs:\n    task (str): The task for {tool_name} to handle"

    return tool_function

def refresh_operators_info() -> str:
    """
    Refresh DataJuicer operators information during runtime.
    
    This function should be called when new operators are developed or when 
    the operator library needs to be updated during the agent's lifecycle.
    
    Returns:
        str: Status message indicating success or failure
    """
    try:
        from data_juicer_agents.tools.op_manager.op_retrieval import refresh_dj_func_info
        
        if refresh_dj_func_info():
            content = "✓ Successfully refreshed DataJuicer operators information. New operators are now available for use."
        else:
            content = "✗ Failed to refresh DataJuicer operators information. Please check the logs for details."
            
    except Exception as e:
        content = f"✗ Error refreshing operators information: {str(e)}"

    finally:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=content,
                ),
            ],
        )