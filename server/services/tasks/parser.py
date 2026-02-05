import shlex
import json
import ast
from typing import Dict, Any, List, Tuple, Optional

class CommandParser:
    """动态命令解析层：支持将字符串指令解析为函数名和动态参数"""
    
    @staticmethod
    def parse(cmd_str: str) -> Optional[Dict[str, Any]]:
        print(f"[Parser] Parsing command: {cmd_str}")
        try:
            # posix=False 保持引号，避免 shlex 自动去掉 target_selectors=['xxx'] 里的单引号
            tokens = shlex.split(cmd_str, posix=False)
        except ValueError as e:
            print(f"[Parser] shlex split error: {e}")
            return None
            
        if not tokens:
            return None
            
        # 聚合被 shlex 拆分的 brackets (针对带空格的 list/dict)
        fixed_tokens = []
        temp_buffer = []
        bracket_depth = 0
        for t in tokens:
            if temp_buffer:
                temp_buffer.append(t)
                bracket_depth += t.count("[") + t.count("{") - t.count("]") - t.count("}")
                if bracket_depth <= 0:
                    fixed_tokens.append(" ".join(temp_buffer))
                    temp_buffer = []
                    bracket_depth = 0
            else:
                if (t.count("[") + t.count("{")) > (t.count("]") + t.count("}")):
                    temp_buffer.append(t)
                    bracket_depth = t.count("[") + t.count("{") - t.count("]") - t.count("}")
                else:
                    fixed_tokens.append(t)
        if temp_buffer: fixed_tokens.append(" ".join(temp_buffer))
        tokens = fixed_tokens

        action_name = tokens[0].lower()
        args = []
        kwargs = {}
        
        # 处理别名
        aliases = {
            "click": "click",        # 映射到通用的 click 函数
            "submit": "click_submit", # 用于发送消息
            "generate": "submit_image_prompt", # 图文复合提交
            "type": "input_prompt",
            "input": "input_prompt",
            "reset": "start_new_chat",
            "new": "start_new_chat",
            "model": "set_model",
            "wait": "sleep" # 需要特殊处理
        }
        
        real_action = aliases.get(action_name, action_name)
        
        for token in tokens[1:]:
            # 只有当 '=' 前面是合法标识符且不含括号时，才视为 kwarg
            # 这样可以避免 selectors=["a=b"] 被识别成 ["a=b"] 是 key
            if "=" in token and not (token.startswith("[") or token.startswith("{")):
                parts = token.split("=", 1)
                key = parts[0].strip()
                # 进一步检查 key 是否像一个参数名 (不含引号、空格、中括号)
                if " " not in key and "[" not in key and "{" not in key and '"' not in key and "'" not in key:
                    kwargs[key] = CommandParser._parse_val(parts[1])
                    continue
            
            args.append(CommandParser._parse_val(token))
        
        result = {
            "action": real_action,
            "args": args,
            "kwargs": kwargs
        }
        print(f"[Parser] Result: {result}")
        return result

    @staticmethod
    def _parse_val(val: str) -> Any:
        """复杂的类型转换，支持 JSON/List/Bool/Int/String"""
        val_clean = val.strip()
        
        # 1. 尝试解析 JSON 或 Python 字面量 (List/Dict)
        if (val_clean.startswith("[") and val_clean.endswith("]")) or \
           (val_clean.startswith("{") and val_clean.endswith("}")):
            try:
                return ast.literal_eval(val_clean)
            except:
                try:
                    return json.loads(val_clean.replace("'", '"'))
                except:
                    pass
        
        # 2. 处理带引号的字符串 (posix=False 会保留引号)
        if (val_clean.startswith('"') and val_clean.endswith('"')) or \
           (val_clean.startswith("'") and val_clean.endswith("'")):
            try:
                return ast.literal_eval(val_clean)
            except:
                return val_clean[1:-1]
        
        # 3. 基础类型转换
        if val_clean.lower() == "true": return True
        if val_clean.lower() == "false": return False
        if val_clean.isdigit(): return int(val_clean)
        
        try:
            return float(val_clean)
        except ValueError:
            return val_clean


