import asyncio
import random
import urllib.parse
from typing import Any, Dict, List, Optional

class ScriptSyntaxError(Exception):
    pass


class Parser:

    def __init__(self, globals_dict: Optional[Dict[str, Any]] = None):
        self.globals: Dict[str, str] = (
            {k: str(v) for k, v in globals_dict.items()}
            if globals_dict
            else {}
        )

        self.variables: Dict[str, str] = {}

        self.functions: Dict[str, tuple[List[str], str]] = {}
        self.default_functions: Dict[str, Any] = {}

        self.local_scopes: List[Dict[str, str]] = []

    async def parse(self, text: str) -> str:
        self.variables = {}
        self.local_scopes = []

        self._check_brackets(text)

        ast = self._build_ast(text)

        return await self._evaluate_ast(ast)

    def _check_brackets(self, text: str) -> None:
        count = 0
        for char in text:
            if char == "{":
                count += 1
            elif char == "}":
                count -= 1
                if count < 0:
                    raise ScriptSyntaxError(
                        "閉じ括弧 '}' が開き括弧 '{' より先に現れました。"
                    )
        if count != 0:
            raise ScriptSyntaxError(
                f"括弧の対応が取れていません。開き括弧が {count} 個多く存在します。"
            )

    def _build_ast(self, text: str) -> List[Any]:
        stack: List[List[Any]] = [[]]
        i = 0
        n = len(text)

        while i < n:
            if text[i] == "{":
                stack.append([])
                i += 1
            elif text[i] == "}":
                if len(stack) <= 1:
                    raise ScriptSyntaxError("不正な閉じ括弧です。")
                completed_expr = stack.pop()
                stack[-1].append({"type": "expression", "content": completed_expr})
                i += 1
            else:
                start = i
                while i < n and text[i] != "{" and text[i] != "}":
                    i += 1
                stack[-1].append(text[start:i])

        return stack[0]

    async def _evaluate_ast(self, ast: List[Any]) -> str:
        result = []
        for node in ast:
            if isinstance(node, str):
                result.append(node)
            elif isinstance(node, dict) and node.get("type") == "expression":
                result.append(await self._execute_expression(node["content"]))
        try:
            return "".join(result)
        except TypeError:
            return ""

    def _clean_token(self, text: str) -> str:
        return text.strip()

    def _split_arguments(self, tokens: List[Any]) -> List[List[Any]]:
        args = []
        current_arg = []
        for token in tokens:
            if isinstance(token, str) and "|" in token:
                parts = token.split("|")
                for j, part in enumerate(parts):
                    if j > 0:
                        args.append(current_arg)
                        current_arg = []
                    current_arg.append(part)
            else:
                current_arg.append(token)
        if current_arg:
            args.append(current_arg)
        return args

    def add_func(self, name: str, func):
        self.default_functions[name] = func

    def _eval_condition(self, cond_str: str) -> bool:
        operators = [">=", "<=", "==", "!=", ">", "<"]
        op_found = None
        
        for op in operators:
            if op in cond_str:
                op_found = op
                break
                
        if not op_found:
            return bool(self._clean_token(cond_str))
            
        left_raw, right_raw = cond_str.split(op_found, 1)
        left = self._clean_token(left_raw)
        right = self._clean_token(right_raw)
        
        if op_found in [">=", "<=", ">", "<"]:
            try:
                l_num = float(left)
                r_num = float(right)
                
                if op_found == ">=": return l_num >= r_num
                if op_found == "<=": return l_num <= r_num
                if op_found == ">":  return l_num > r_num
                if op_found == "<":  return l_num < r_num
            except ValueError:
                return False
                
        if op_found == "==":
            return left == right
        if op_found == "!=":
            return left != right
            
        return False

    async def _execute_expression(self, tokens: List[Any]) -> str:
        raw_args = self._split_arguments(tokens)

        if not raw_args:
            return ""

        first_arg_tokens = raw_args[0]
        first_token_str = ""
        for t in first_arg_tokens:
            if isinstance(t, str):
                first_token_str += t
            else:
                first_token_str += await self._evaluate_ast([t])

        first_token_str = self._clean_token(first_token_str)

        if ":" in first_token_str:
            command, main_arg = first_token_str.split(":", 1)
            command = self._clean_token(command)
            main_arg = self._clean_token(main_arg)

            if command == "if":
                current_cond = (await self._evaluate_ast(first_arg_tokens)).split(":", 1)[1]
                
                if self._eval_condition(current_cond):
                    return await self._evaluate_ast(raw_args[1]) if len(raw_args) > 1 else ""
                
                idx = 2
                while idx < len(raw_args):
                    block_head = await self._evaluate_ast(raw_args[idx])
                    cleaned_head = self._clean_token(block_head)
                    
                    if cleaned_head.startswith("elif:"):
                        cond_part = cleaned_head.split(":", 1)[1]
                        if self._eval_condition(cond_part):
                            if idx + 1 < len(raw_args):
                                return await self._evaluate_ast(raw_args[idx + 1])
                            return ""
                        idx += 2
                    elif cleaned_head == "else":
                        if idx + 1 < len(raw_args):
                            return await self._evaluate_ast(raw_args[idx + 1])
                        return ""
                    else:
                        idx += 1
                return ""

            elif command == "func":
                func_name = main_arg
                arg_names = []
                func_body_tokens = []

                if len(raw_args) >= 3:
                    raw_arg_names = await self._evaluate_ast(raw_args[1])
                    arg_names = [
                        self._clean_token(a) for a in raw_arg_names.split(",") if a
                    ]
                    func_body_tokens = raw_args[2]
                elif len(raw_args) == 2:
                    func_body_tokens = raw_args[1]

                self.functions[func_name] = (arg_names, func_body_tokens)
                return ""

            else:
                evaluated_tail_args = [
                    (await self._evaluate_ast(arg)).strip() for arg in raw_args[1:]
                ]

                if command == "set":
                    val = evaluated_tail_args[0] if evaluated_tail_args else ""
                    self.variables[main_arg] = val
                    return ""

                elif command == "get":
                    return self._get_variable(main_arg)

                elif command == "call":
                    func_name = main_arg
                    if func_name not in self.functions:
                        return ""

                    arg_names, body_tokens = self.functions[func_name]
                    call_args = evaluated_tail_args

                    local_scope = {}
                    for idx, name in enumerate(arg_names):
                        local_scope[name] = (
                            call_args[idx] if idx < len(call_args) else ""
                        )

                    self.local_scopes.append(local_scope)
                    try:
                        result = await self._evaluate_ast(body_tokens)
                    finally:
                        self.local_scopes.pop()
                    return result

                elif command == "random":
                    try:
                        low, high = map(int, main_arg.split("~"))
                        return str(random.randint(low, high))
                    except Exception:
                        return ""

                elif command == "choice":
                    choices = [main_arg] + evaluated_tail_args
                    choices = [c for c in choices if c]
                    return random.choice(choices) if choices else ""

                elif command == "urlencode":
                    return urllib.parse.quote(main_arg)

                else:
                    if not self.default_functions.get(command):
                        return ""
                    try:
                        return await self.default_functions.get(command)(self.globals, [main_arg] + evaluated_tail_args)
                    except:
                        return ""

        else:
            var_name = first_token_str
            return self._get_variable(var_name)

        return ""

    def _get_variable(self, name: str) -> str:
        if self.local_scopes:
            for scope in reversed(self.local_scopes):
                if name in scope:
                    return scope[name]

        if name in self.variables:
            return self.variables[name]

        if name in self.globals:
            return self.globals[name]

        return ""
    
if __name__ == "__main__":
    text = """
ユーザー名: {name}
ユーザーID: {tarou}
"""

    async def run():
        parser = Parser({
            "name": "太郎",
            "id": "tarou123"
        })
        print((await parser.parse(text)).strip())

    asyncio.run(run())