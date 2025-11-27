# -*- coding: utf-8 -*-
import asyncio
from typing import Optional, List
from pydantic import BaseModel
import json
import os
import subprocess
import shutil

from agent_run import agent, toolkit, mcp_clients
from agentscope_runtime.engine.app import AgentApp
from agentscope_runtime.engine.deployers.local_deployer import LocalDeployManager
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest, Message
from agentscope_runtime.engine.services.redis_memory_service import RedisMemoryService
from agentscope_runtime.engine.services.context_manager import ContextManager
from typing import Dict, Any
from agentscope_runtime.engine.services.session_history_service import InMemorySessionHistoryService

DATA_JUICER_PATH = os.getenv("DATA_JUICER_PATH")

class MessageWithFeedback(Message):
    """Extended Message class with feedback support."""
    feedback: Optional[Dict[str, Any]] = None


class FeedbackRedisMemoryService(RedisMemoryService):
    """Redis memory service with feedback support."""
    
    def _serialize(self, messages: List[MessageWithFeedback]) -> str:
        """Serialize messages with feedback to JSON."""
        return json.dumps([msg.model_dump() for msg in messages], ensure_ascii=False)

    def _deserialize(self, messages_json: str) -> List[MessageWithFeedback]:
        """Deserialize JSON to messages with feedback."""
        if not messages_json:
            return []
        return [MessageWithFeedback.model_validate(m) for m in json.loads(messages_json)]
    
    async def add_memory(
        self,
        user_id: str,
        messages: list,
        session_id: Optional[str] = None,
    ) -> None:
        if messages is None:
            return
        if not self._redis:
            raise RuntimeError("Redis connection is not available")
        key = self._user_key(user_id)
        field = session_id if session_id else self._DEFAULT_SESSION_ID

        existing_json = await self._redis.hget(key, field)
        existing_msgs = self._deserialize(existing_json)
        all_msgs = existing_msgs + messages
        await self._redis.hset(key, field, self._serialize(all_msgs))

    async def update_message_feedback(
        self,
        user_id: str,
        msg_id: str,
        feedback: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> bool:
        """
        Updates the feedback for a specific message.

        Args:
            user_id (str): The ID of the user
            msg_id (str): The ID of the message to update
            feedback (Dict[str, Any]): The feedback data to add
            session_id (Optional[str]): The session ID. If None, searches all sessions

        Returns:
            bool: True if message was found and updated, False otherwise
        """
        if not self._redis:
            raise RuntimeError("Redis connection is not available")

        key = self._user_key(user_id)

        # Determine which sessions to search
        if session_id:
            sessions_to_search = [session_id]
        else:
            sessions_to_search = await self._redis.hkeys(key)

        # Search for the message in sessions
        for sid in sessions_to_search:
            msgs_json = await self._redis.hget(key, sid)
            if not msgs_json:
                continue

            msgs = self._deserialize(msgs_json)
            message_found = False

            # Find and update the message
            for msg in msgs:
                if msg.id == msg_id:
                    msg.feedback = feedback
                    message_found = True
                    break

            if message_found:
                # Save updated messages back to Redis
                await self._redis.hset(key, sid, self._serialize(msgs))
                return True

        return False

# Initialize services
session_history_service = InMemorySessionHistoryService()
redis_memory_service = FeedbackRedisMemoryService()


class FeedbackRequest(BaseModel):
    message_id: str
    feedback: str  # 'like' or 'dislike'
    session_id: str
    user_id: str = ""  # Default to empty string for compatibility
    timestamp: Optional[int] = None


async def init_resources(app, **kwargs):
    serena_config_path = os.path.join(DATA_JUICER_PATH, ".serena")
    if not os.path.exists(DATA_JUICER_PATH):
        print("Cloning data-juicer repository...")
        try:
            subprocess.run(["git", "clone", "--depth", "1", "https://github.com/datajuicer/data-juicer.git", f"{DATA_JUICER_PATH}"], check=True)
            print("✅ Successfully cloned data-juicer repository")
            
            if os.path.exists("./config/.serena"):
                try:
                    shutil.copytree("./config/.serena", serena_config_path, dirs_exist_ok=True)
                    print("✅ Successfully copied .serena configuration to data-juicer")
                except Exception as e:
                    print(f"⚠️ Failed to copy .serena configuration: {e}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to clone data-juicer repository: {e}")
    else:
        print("📁 data-juicer directory already exists")
        
        if not os.path.exists(serena_config_path) and os.path.exists("./config/.serena"):
            try:
                shutil.copytree("./config/.serena", serena_config_path, dirs_exist_ok=True)
                print("✅ Successfully copied .serena configuration to data-juicer")
            except Exception as e:
                print(f"⚠️ Failed to copy .serena configuration: {e}")
    
    print("🚀 Connecting to Redis...")
    await redis_memory_service.start()

    if mcp_clients:
        for mcp_client in mcp_clients:
            print("🚀 Connecting to MCP server...")
            await mcp_client.connect()
            await toolkit.register_mcp_client(mcp_client)


async def cleanup_resources(app, **kwargs):
    print("🛑 Shutting down Redis...")
    await redis_memory_service.stop()

    if mcp_clients:
        for mcp_client in mcp_clients:
            print("🛑 Disconnecting from MCP server...")
            await mcp_client.close()


context_manager = ContextManager(
    memory_service=redis_memory_service,
    session_history_service=session_history_service,
)

app = AgentApp(
    agent=agent,
    before_start=init_resources,
    after_finish=cleanup_resources,
    context_manager=context_manager,
)


@app.endpoint("/memory")
async def get_memory(request: AgentRequest):
    """Retrieve conversation history for a session."""
    session_id = request.session_id
    print(f"📥 Fetching memory for session: {session_id}")

    memories = await session_history_service.get_session("", session_id)
    messages = []

    for msg in memories.messages:
        content_text = ""
        if hasattr(msg, 'content'):
            if isinstance(msg.content, list):
                for item in msg.content:
                    if getattr(item, 'type', None) == 'text':
                        content_text += getattr(item, 'text', '')
            elif isinstance(msg.content, str):
                content_text = msg.content

        if content_text.strip() and hasattr(msg, 'role'):
            messages.append({
                "role": msg.role,
                "content": content_text.strip()
            })

    response = {"messages": messages}
    print(f"📤 Returning {len(messages)} messages")
    return response


@app.endpoint("/clear")
async def clear_memory(request: AgentRequest):
    """Clear conversation history for a session."""
    session_id = request.session_id
    print(f"🧹 Clearing memory for session: {session_id}")
    await session_history_service.delete_session("", session_id)
    return {"status": "ok"}


@app.endpoint("/feedback")
async def handle_feedback(request: FeedbackRequest):
    """Record user feedback (like/dislike) for a message."""
    message_id = request.message_id
    session_id = request.session_id
    user_id = request.user_id
    feedback_data = {
        "type": request.feedback,
        "timestamp": request.timestamp
    }
    
    try:
        # Update feedback in Redis memory
        success = await redis_memory_service.update_message_feedback(
            user_id=user_id,
            msg_id=message_id,
            feedback=feedback_data,
            session_id=session_id
        )
        
        if success:
            return {
                "status": "ok",
                "message": "Feedback recorded successfully",
                "message_id": message_id
            }
        else:
            return {
                "status": "error",
                "message": "Message not found",
                "message_id": message_id
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to save feedback: {str(e)}",
            "message_id": message_id
        }


async def main():
    """Deploy the agent application in detached mode."""
    print("🚀 Starting AgentApp deployment...")

    deploy_manager = LocalDeployManager(
        host="127.0.0.1",
        port=8080,
        startup_timeout=500,
    )

    deployment_info = await deploy_manager.deploy(app=app)
    url = deployment_info['url']
    deploy_id = deployment_info['deploy_id']

    print(f"✅ Deployment successful: {url}")
    print(f"📍 Deployment ID: {deploy_id}")

    import socket
    local_ip = socket.gethostbyname(socket.gethostname())

    print(f"""
📡 Access URLs:
   - Local: http://localhost:8080
   - LAN:   http://{local_ip}:8080
   - Public: http://YOUR_PUBLIC_IP:8080

🎯 Test commands:
   curl {url}/health
   curl -X POST {url}/admin/shutdown

⚠️ The service runs in a detached process and persists until explicitly stopped.
""")

if __name__ == "__main__":
    asyncio.run(main())
    input("Press Enter to terminate the server...")