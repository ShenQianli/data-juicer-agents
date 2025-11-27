# -*- coding: utf-8 -*-
import os
import os.path as osp
import re
import asyncio
from typing import Any, List
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

async def execute_safe_command(
    command: str,
    timeout: int = 300,
    **kwargs: Any,
) -> ToolResponse:
    """Execute safe commands including DataJuicer commands and other safe system commands.
    Returns the return code, standard output and error within <returncode></returncode>,
    <stdout></stdout> and <stderr></stderr> tags.

    Args:
        command (`str`):
            The command to execute. Allowed commands include:
            - DataJuicer commands: dj-process, dj-analyze
            - File system commands: mkdir, ls, pwd, cat, echo, cp, mv, rm
            - Text processing: grep, head, tail, wc, sort, uniq
            - Archive commands: tar, zip, unzip
            - Other safe commands: which, whoami, date, find
        timeout (`float`, defaults to `300`):
            The maximum time (in seconds) allowed for the command to run.

    Returns:
        `ToolResponse`:
            The tool response containing the return code, standard output, and
            standard error of the executed command.
    """

    # Security check: only allow safe commands
    command_stripped = command.strip()

    # Define allowed command prefixes for security
    allowed_commands = [
        # DataJuicer commands
        "dj-process",
        "dj-analyze",
        # File system operations
        "mkdir",
        "ls",
        "pwd",
        "cat",
        "echo",
        "cp",
        "mv",
        "rm",
        # Text processing
        "grep",
        "head",
        "tail",
        "wc",
        "sort",
        "uniq",
        # Archive operations
        "tar",
        "zip",
        "unzip",
        # Information commands
        "which",
        "whoami",
        "date",
        "find",
        # Python commands
        "python",
        "python3",
        "pip",
        "uv",
    ]

    # Check if command starts with any allowed command
    command_allowed = False
    for allowed_cmd in allowed_commands:
        if command_stripped.startswith(allowed_cmd):
            # Additional security checks for potentially dangerous commands
            if allowed_cmd in ["rm", "mv"] and (
                "/" in command_stripped or ".." in command_stripped
            ):
                # Prevent dangerous path operations
                continue
            command_allowed = True
            break

    if not command_allowed:
        error_msg = f"Error: Command not allowed for security reasons. Allowed commands: {', '.join(allowed_commands)}. Received command: {command}"
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"<returncode>-1</returncode>"
                        f"<stdout></stdout>"
                        f"<stderr>{error_msg}</stderr>"
                    ),
                ),
            ],
        )

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        bufsize=0,
    )

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
        stdout, stderr = await proc.communicate()
        stdout_str = stdout.decode("utf-8")
        stderr_str = stderr.decode("utf-8")
        returncode = proc.returncode

    except asyncio.TimeoutError:
        stderr_suffix = (
            f"TimeoutError: The command execution exceeded "
            f"the timeout of {timeout} seconds."
        )
        returncode = -1
        try:
            proc.terminate()
            stdout, stderr = await proc.communicate()
            stdout_str = stdout.decode("utf-8")
            stderr_str = stderr.decode("utf-8")
            if stderr_str:
                stderr_str += f"\n{stderr_suffix}"
            else:
                stderr_str = stderr_suffix
        except ProcessLookupError:
            stdout_str = ""
            stderr_str = stderr_suffix

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=(
                    f"<returncode>{returncode}</returncode>"
                    f"<stdout>{stdout_str}</stdout>"
                    f"<stderr>{stderr_str}</stderr>"
                ),
            ),
        ],
    )


async def get_ops_signature(op_names: List[str]) -> ToolResponse:
    """Get detailed information for specified DataJuicer operators.
    
    This tool retrieves comprehensive operator metadata including signatures, 
    parameter descriptions, and usage information. It's designed to help the 
    data processing agent generate accurate YAML configuration files.

    Args:
        op_names (List[str]): List of operator names to query (e.g., ['text_length_filter', 'image_shape_filter'])

    Returns:
        ToolResponse: Detailed operator information including:
            - Operator type (Filter/Mapper/Deduplicator)
            - Function signature with parameter types
            - Parameter descriptions and default values
            - Usage examples or constraints
    
    Example:
        >>> get_ops_signature(['text_length_filter', 'image_face_count_filter'])
        Returns detailed configuration info for both operators
    """
    try:
        from data_juicer.tools.op_search import OPSearcher
        
        # Initialize OPSearcher
        searcher = OPSearcher(include_formatter=False)
        records_map = searcher.records_map
        
        if not op_names:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="Error: op_names list is empty. Please provide at least one operator name.",
                    ),
                ],
            )
        
        # Collect operator details
        operators_info = []
        not_found = []
        
        for op_name in op_names:
            if op_name in records_map:
                record = records_map[op_name]
                simple_desc = record.desc.split("\n")[0]
                
                # Format signature information
                sig_str = str(record.sig)
                
                # Build detailed parameter information
                param_details = []
                for item in record.param_desc.split(":param"):
                    _item = item.split(":")
                    if len(_item) < 2:
                        continue
                    param_details.append(f"  - {_item[0].strip()}: {':'.join(_item[1:]).strip()}")
                
                # Format operator information
                op_info = f"""
{'='*60}
Operator: {record.name}
Desc: {simple_desc}
Type: {record.type}
Tags: {', '.join(record.tags) if record.tags else 'None'}

Signature:
{sig_str}

Parameters:
{chr(10).join(param_details) if param_details else '  No parameters'}
{'='*60}
"""
                operators_info.append(op_info)
            else:
                not_found.append(op_name)
        
        # Build response text
        result_text = "🔍 DataJuicer Operator Details\n\n"
        
        if operators_info:
            result_text += f"Found {len(operators_info)} operator(s):\n"
            result_text += "\n".join(operators_info)
        
        if not_found:
            result_text += f"\n⚠️  Operators not found: {', '.join(not_found)}\n"
            result_text += "Please check operator names or ask router\n"
        
        return ToolResponse(
            content=[TextBlock(type="text", text=result_text)],
        )
        
    except ImportError as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Failed to import OPSearcher. Please ensure data_juicer is properly installed.\nDetails: {str(e)}",
                ),
            ],
        )
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error occurred while getting operator signatures: {str(e)}",
                ),
            ],
        )

async def get_advanced_config_info(config_type: str = "all") -> ToolResponse:
    """Get advanced DataJuicer configuration information from local installation.
    
    This tool retrieves advanced configuration options that go beyond the basic
    YAML template, enabling more sophisticated data processing scenarios.
    
    Args:
        config_type (str): Type of configuration to retrieve. Options:
            - "global": Get additional global parameters from config_all.yaml
            - "dataset": Get flexible dataset configuration from DatasetCfg.md
            - "all": Get both global parameters and dataset configuration
            Defaults to "all".
    
    Returns:
        ToolResponse: Advanced configuration information formatted as Markdown,
            including parameter descriptions, default values, and usage examples.
    
    Note:
        This tool requires DATA_JUICER_PATH to be configured. If not configured,
        it will return an error message prompting the user to set up the path
        through the router agent.
    
    Example:
        >>> get_advanced_config_info(config_type="global")
        Returns global parameters from config_all.yaml
        
        >>> get_advanced_config_info(config_type="dataset")
        Returns dataset configuration documentation
    """
    try:
        DATA_JUICER_PATH = os.getenv("DATA_JUICER_PATH", None)
        
        # Check if DATA_JUICER_PATH is configured
        if DATA_JUICER_PATH is None:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "DATA_JUICER_PATH is not configured.\n"
                            "Please ask the user to provide the DataJuicer installation path.\n"
                            "The router agent can help configure it using configure_data_juicer_path tool."
                        ),
                    ),
                ],
            )
        
        # Validate config_type parameter
        valid_types = ["global", "dataset", "all"]
        if config_type not in valid_types:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Invalid config_type: {config_type}. Must be one of: {', '.join(valid_types)}",
                    ),
                ],
            )
        
        result_text = "# DataJuicer Advanced Configuration\n\n"
        
        # Read global parameters from config_all.yaml
        if config_type in ["global", "all"]:
            config_all_path = osp.join(DATA_JUICER_PATH, "configs", "config_all.yaml")
            
            if osp.exists(config_all_path):
                try:
                    from ruamel.yaml import YAML
                    from io import StringIO
                    
                    yaml = YAML()
                    yaml.preserve_quotes = True
                    yaml.indent(mapping=2, sequence=4, offset=2)
                    
                    with open(config_all_path, "r", encoding="utf-8") as f:
                        config_data = yaml.load(f)
                    
                    # Remove 'process' key to get true global parameters
                    if isinstance(config_data, dict) and 'process' in config_data:
                        del config_data['process']
                    
                    # Convert back to YAML string with preserved comments
                    stream = StringIO()
                    yaml.dump(config_data, stream)
                    config_content = stream.getvalue()
                    
                    patterns_to_remove = [
                        r'^[ \t]*#[ \t]*-[ \t]*all ops and their arguments[ \t]*\n?',
                        r'^[ \t]*#[ \t]*process schedule:[ \t]*a list of several process operators with their arguments[ \t]*\n?'
                    ]
                    for pattern in patterns_to_remove:
                        config_content = re.sub(pattern, '', config_content, flags=re.MULTILINE)
                    
                    result_text += "## Global Parameters (from config_all.yaml)\n\n"
                    result_text += "These are additional global parameters beyond the basic template:\n\n"
                    result_text += "```yaml\n"
                    result_text += config_content
                    result_text += "```\n\n"
                    
                except Exception as e:
                    result_text += f"⚠️  Failed to read config_all.yaml: {str(e)}\n\n"
            else:
                result_text += f"⚠️  config_all.yaml not found at: {config_all_path}\n"
                result_text += "Please check your DataJuicer installation.\n\n"
        
        # Read dataset configuration from DatasetCfg.md
        if config_type in ["dataset", "all"]:
            dataset_cfg_path = osp.join(DATA_JUICER_PATH, "docs", "DatasetCfg.md")
            
            if osp.exists(dataset_cfg_path):
                try:
                    with open(dataset_cfg_path, "r", encoding="utf-8") as f:
                        dataset_content = f.read()
                    
                    result_text += "## Dataset Configuration (from DatasetCfg.md)\n\n"
                    result_text += "Flexible dataset configuration options:\n\n"
                    result_text += "---\n\n"
                    result_text += dataset_content
                    result_text += "\n\n---\n\n"
                    
                except Exception as e:
                    result_text += f"⚠️  Failed to read DatasetCfg.md: {str(e)}\n\n"
            else:
                result_text += f"⚠️  DatasetCfg.md not found at: {dataset_cfg_path}\n"
                result_text += "Please check your DataJuicer installation.\n\n"
        
        return ToolResponse(
            content=[TextBlock(type="text", text=result_text)],
        )
        
    except ImportError as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Failed to import DATA_JUICER_PATH: {str(e)}",
                ),
            ],
        )
    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error occurred while getting advanced config info: {str(e)}",
                ),
            ],
        )