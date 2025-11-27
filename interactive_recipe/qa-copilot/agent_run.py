# -*- coding: utf-8 -*-
import asyncio
import os
import prompts

from agentscope.mcp import StdIOStatefulClient
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit, view_text_file
from agentscope.agent import ReActAgent
from agentscope_runtime.engine.agents.agentscope_agent import AgentScopeAgent
from agentscope_runtime.engine.runner import Runner
from agentscope_runtime.engine.schemas.agent_schemas import (
    MessageType,
    RunStatus,
    AgentRequest,
)
import copy
from agentscope_runtime.engine.services.context_manager import ContextManager

# from file_tracking_agent import FileTrackingReActAgent


DATA_JUICER_PATH = os.getenv("DATA_JUICER_PATH", "/app/data-juicer")


class DeepCopyableToolkit(Toolkit):
    def __deepcopy__(self, memo):
        new_toolkit = DeepCopyableToolkit()

        for key, value in self.__dict__.items():
            try:
                new_toolkit.__dict__[key] = copy.deepcopy(value, memo)
            except (TypeError, AttributeError):
                # Fallback to shallow copy for non-deepcopyable objects
                if isinstance(value, (dict, list, set)):
                    new_toolkit.__dict__[key] = value.copy()
                else:
                    new_toolkit.__dict__[key] = value

        memo[id(self)] = new_toolkit
        return new_toolkit


toolkit = DeepCopyableToolkit()
toolkit.register_tool_function(view_text_file)

agent = AgentScopeAgent(
    name="Juicer",
    model=DashScopeChatModel(
        "qwen-max",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        stream=True,
    ),
    agent_config={
        "sys_prompt": prompts.QA,
        "toolkit": toolkit,
    },
    agent_builder=ReActAgent,
)

serena_command = [
    "uvx",
    "--with",
    "pyright[nodejs]",
    "--from",
    "git+https://github.com/oraios/serena",
    "serena",
    "start-mcp-server",
    "--project",
    DATA_JUICER_PATH,
    "--mode",
    "planning",
]

mcp_clients = []

mcp_clients.append(
    StdIOStatefulClient(
        name="Serena",
        command=serena_command[0],
        args=serena_command[1:],
    )
)


async def chat_loop():
    """Multi-turn conversation loop"""
    print("🚀 Connecting to MCP server...")
    for mcp_client in mcp_clients:
        await mcp_client.connect()

        # Register MCP tools with error handling
        try:
            await toolkit.register_mcp_client(mcp_client)
            print("✅ MCP tools registered")
        except ValueError as e:
            if "already registered" in str(e):
                print(f"⚠️ {e}")
            else:
                raise

    context_manager = ContextManager()
    runner = Runner(agent=agent, context_manager=context_manager)

    # Generate session_id for conversation continuity
    import uuid

    session_id = f"console-{uuid.uuid4()}"

    print("\n" + "=" * 60)
    print("🤖 Juicer Agent - Chat Mode")
    print("=" * 60)
    print("Commands: 'exit/quit' | 'clear' | 'tools'")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("👤 You: ").strip()

            if user_input.lower() in ["exit", "quit", "q"]:
                print("\n👋 Closing...")
                break

            if user_input.lower() == "clear":
                session_id = f"console-{uuid.uuid4()}"
                print("🧹 History cleared\n")
                continue

            if user_input.lower() == "tools":
                print("\n🔧 Available tools:")
                for tool in toolkit.get_tools():
                    print(f"  - {tool['name']}: {tool.get('description', 'N/A')}")
                print()
                continue

            if not user_input:
                continue

            request = AgentRequest(
                input=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": user_input}],
                    }
                ],
                session_id=session_id,
            )

            print("🤖 Juicer: ", end="", flush=True)

            # Stream response
            all_result = ""
            async for message in runner.stream_query(request=request):
                if message.object == "message" and message.type == MessageType.MESSAGE:
                    if message.status == RunStatus.InProgress:
                        if message.content and len(message.content) > 0:
                            chunk = message.content[0].text
                            if chunk and chunk != all_result:
                                print(chunk[len(all_result) :], end="", flush=True)
                                all_result = chunk

                    elif message.status == RunStatus.Completed:
                        if message.content and len(message.content) > 0:
                            final_text = message.content[0].text
                            if final_text != all_result:
                                print(final_text[len(all_result) :], end="", flush=True)

            print("\n")

        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 Exiting...")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}\n")
            import traceback

            traceback.print_exc()

    # Cleanup
    for mcp_client in mcp_clients:
        try:
            await mcp_client.close()
            print("✅ Connection closed")
        except Exception as e:
            print(f"⚠️ Error closing connection: {e}")


async def run_single_query():
    """Single query mode"""
    for mcp_client in mcp_clients:
        await mcp_client.connect()

        try:
            await toolkit.register_mcp_client(mcp_client)
            print("✅ MCP tools registered")
        except ValueError as e:
            if "already registered" in str(e):
                print(f"⚠️ {e}")
            else:
                raise

    request = AgentRequest(
        input=[
            {
                "role": "user",
                "content": [{"type": "text", "text": "What tools are available?"}],
            }
        ],
    )

    runner = Runner(agent=agent, context_manager=ContextManager())

    all_result = ""
    async for message in runner.stream_query(request=request):
        if (
            message.object == "message"
            and message.type == MessageType.MESSAGE
            and message.status == RunStatus.Completed
        ):
            all_result = message.content[0].text
        print(message)

    print(f"📝 Response: {all_result}")
    for mcp_client in mcp_clients:
        await mcp_client.close()


if __name__ == "__main__":
    asyncio.run(chat_loop())
    # asyncio.run(run_single_query())  # Alternative: single query mode
