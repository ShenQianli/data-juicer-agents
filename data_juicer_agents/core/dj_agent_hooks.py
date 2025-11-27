# -*- coding: utf-8 -*-
"""
DataJuicer Agent Hooks

Hook functions for cleaning and processing agent outputs.
"""

from typing import Any

def clean_log(log_content):
    """
    Clean log content:
    1. Extract configuration information (remove table lines)
    2. Remove all progress bars
    3. Remove duplicate lines
    4. Remove data_juicer.ops:timing_context lines
    """
    lines = log_content.split('\n')
    cleaned = []
    seen_lines = set()
    
    # Status flags
    in_config_table = False
    current_config_key = None
    current_config_value = []
    downloading_shown = False
    
    for line in lines:
        stripped = line.strip()
        
        # ===== Handle configuration table =====
        if '╒══════════════════════════╤' in line or '│ key' in line and in_config_table is False:
            in_config_table = True
            cleaned.append("\n" + "=" * 60)
            cleaned.append("📋 CONFIGURATION:")
            cleaned.append("=" * 60)
            continue
        
        if in_config_table:
            if any(char in line for char in ['╒', '╞', '├', '╘', '═', '─']) and '│' not in line:
                continue
            
            if '╘══════' in line:
                if current_config_key:
                    cleaned.append(f"{current_config_key}: {' '.join(current_config_value)}")
                    current_config_key = None
                    current_config_value = []
                
                in_config_table = False
                cleaned.append("=" * 60 + "\n")
                continue
            
            if '│' in line:
                parts = line.split('│')
                if len(parts) >= 3:
                    key = parts[1].strip()
                    value = parts[2].strip()
                    
                    if key == 'key' or (key == '' and value == 'values'):
                        continue
                    
                    if key:
                        if current_config_key:
                            cleaned.append(f"{current_config_key}: {' '.join(current_config_value)}")
                        
                        current_config_key = key
                        current_config_value = [value] if value else []
                    else:
                        if value and current_config_key:
                            current_config_value.append(value)
                continue
        
        if 'data_juicer.ops:timing_context' in line:
            continue
        
        if '%|' in line or 'examples/s]' in line or (stripped and stripped.endswith('%')):
            continue
        
        # ===== Handle Downloading lines =====
        if 'Downloading' in line:
            if not downloading_shown:
                cleaned.append(line)
                seen_lines.add(line)
                downloading_shown = True
                # Add ellipsis hint
                cleaned.append('... (more downloading logs omitted)')
            continue
        
        # ===== Deduplicate and keep other content =====
        if line not in seen_lines:
            cleaned.append(line)
            seen_lines.add(line)
    
    return '\n'.join(cleaned)


async def dj_agent_post_acting_clean_content(
    self: "ReActAgent",  # pylint: disable=W0613
    *args: Any,
    **kwargs: Any,
) -> None:
    """
    Hook function for cleaning messy shell command output after action.
    Specifically designed to clean DataJuicer processing logs and other shell outputs.
    
    This hook will:
    1. Extract configuration information (remove table lines)
    2. Remove all progress bars
    3. Remove duplicate lines
    4. Remove data_juicer.ops:timing_context lines
    5. Keep only one Downloading line, replace others with ellipsis
    """
    print("dj_agent_post_acting_clean_content")
    mem_msgs = await self.memory.get_memory()
    mem_length = await self.memory.size()
    if len(mem_msgs) == 0:
        return
    
    last_output_msg = mem_msgs[-1]
    
    # Process each content block in the message
    for i, content_block in enumerate(last_output_msg.content):
        if content_block.get("type") == "tool_result":
            # Check if this is output from execute_safe_command or similar shell tools
            tool_name = content_block.get("name", "")
            if tool_name in ["execute_safe_command"] or "shell" in tool_name.lower():
                
                # Process the output content
                output_list = content_block.get("output", [])
                for j, output_item in enumerate(output_list):
                    if isinstance(output_item, dict) and output_item.get("type") == "text":
                        # Get the text content from the structure
                        text_content = output_item.get("text", "")
                        
                        # Clean the text content if found
                        if text_content and isinstance(text_content, str):
                            # Apply the clean_log function to clean the shell output
                            cleaned_content = clean_log(text_content)
                            
                            # Update the content with cleaned version
                            last_output_msg.content[i]["output"][j]["text"] = cleaned_content
    
    # Update the memory with cleaned message
    await self.memory.delete(mem_length - 1)
    await self.memory.add(last_output_msg)


def register_dj_agent_hooks(agent):
    """
    Register cleaning hooks for DataJuicer agent.
    
    Args:
        agent: ReActAgent instance to register hooks for
    """
    # Register the post-acting hook to clean shell command outputs
    agent.register_instance_hook(
        "post_acting",
        "dj_agent_post_acting_clean_content", 
        dj_agent_post_acting_clean_content,
    )
