"""Terminal rendering for multi-agent-chat."""

import shutil
from .command_parser import Command


class CLIRenderer:
    """Handles all terminal output formatting."""
    
    # ANSI color codes
    C_RESET = "\033[0m"
    C_BOLD = "\033[1m"
    C_DIM = "\033[2m"
    C_GREEN = "\033[32m"
    C_YELLOW = "\033[33m"
    C_BLUE = "\033[34m"
    C_CYAN = "\033[36m"
    C_RED = "\033[31m"
    C_MAGENTA = "\033[35m"
    
    @staticmethod
    def banner():
        """Display welcome banner."""
        width = shutil.get_terminal_size().columns
        print()
        print(f"{CLIRenderer.C_CYAN}{CLIRenderer.C_BOLD}╔{'═' * (width - 2)}╗")
        print(f"║{'Multi-Agent Chat v2.0 (True Agents)'.center(width - 2)}║")
        print(f"╚{'═' * (width - 2)}╝{CLIRenderer.C_RESET}")
        print()
        print(f"  {CLIRenderer.C_DIM}Type /help for commands, /quit to exit{CLIRenderer.C_RESET}")
        print()
    
    @staticmethod
    def help_text():
        """Display help."""
        print(f"""
{CLIRenderer.C_BOLD}Profile 管理:{CLIRenderer.C_RESET}

  {CLIRenderer.C_CYAN}/profile list{CLIRenderer.C_RESET}              List all available profiles
  {CLIRenderer.C_CYAN}/profile -t <name>{CLIRenderer.C_RESET}         邀请 profile 进入群聊
  {CLIRenderer.C_CYAN}/profile -m <name>{CLIRenderer.C_RESET}         将 profile 移出群聊
  {CLIRenderer.C_CYAN}/profile -t list{CLIRenderer.C_RESET}           查看群成员和状态

{CLIRenderer.C_BOLD}发言控制:{CLIRenderer.C_RESET}

  {CLIRenderer.C_CYAN}/profile -t <name> -<N>{CLIRenderer.C_RESET}    设置发言顺序 (1-based)
  {CLIRenderer.C_CYAN}/profile mode <mode>{CLIRenderer.C_RESET}       设置模式: free | mention | ordered
  {CLIRenderer.C_CYAN}/profile order off{CLIRenderer.C_RESET}         清除发言顺序

{CLIRenderer.C_BOLD}管理功能:{CLIRenderer.C_RESET}

  {CLIRenderer.C_CYAN}/admin <name>{CLIRenderer.C_RESET}              设置群管理员
  {CLIRenderer.C_CYAN}/goal <目标描述>{CLIRenderer.C_RESET}           设定群聊目标
  {CLIRenderer.C_CYAN}/goal{CLIRenderer.C_RESET}                      查看目标进度
  {CLIRenderer.C_CYAN}/interrupt{CLIRenderer.C_RESET}                 打断当前发言

{CLIRenderer.C_BOLD}对话:{CLIRenderer.C_RESET}
  {CLIRenderer.C_CYAN}<消息>{CLIRenderer.C_RESET}                    发送群聊消息
  {CLIRenderer.C_CYAN}@<name> <消息>{CLIRenderer.C_RESET}            向指定 profile 发消息

{CLIRenderer.C_BOLD}系统:{CLIRenderer.C_RESET}
  {CLIRenderer.C_CYAN}/help{CLIRenderer.C_RESET}                      Show this help
  {CLIRenderer.C_CYAN}/quit{CLIRenderer.C_RESET}                      Exit
""")
    
    @staticmethod
    def profile_list(profiles):
        """Display profile list."""
        print(f"\n{CLIRenderer.C_BOLD}📋 Available Profiles:{CLIRenderer.C_RESET}\n")
        if not profiles:
            print(f"  {CLIRenderer.C_DIM}(none found){CLIRenderer.C_RESET}")
            return
        
        for p in profiles:
            name = f"{CLIRenderer.C_CYAN}{p.name}{CLIRenderer.C_RESET}"
            display = f"{CLIRenderer.C_BOLD}{p.display_name}{CLIRenderer.C_RESET}" if p.display_name else ""
            role = f"{CLIRenderer.C_DIM}{p.role}{CLIRenderer.C_RESET}" if p.role else ""
            parts = [name]
            if display:
                parts.append(display)
            if role:
                parts.append(role)
            print(f"  {' · '.join(parts)}")
        print()
    
    @staticmethod
    def member_list(members, mode="free", order=None):
        """Display current chat members."""
        print(f"\n{CLIRenderer.C_BOLD}👥 Chat Room ({len(members)} members){CLIRenderer.C_RESET}")
        print(f"   Mode: {CLIRenderer.C_YELLOW}{mode.upper()}{CLIRenderer.C_RESET}")
        
        if not members:
            print(f"  {CLIRenderer.C_DIM}(empty){CLIRenderer.C_RESET}")
            return
        
        if order:
            ordered = sorted(members, key=lambda m: order.get(m.name, 999))
            for i, m in enumerate(ordered, 1):
                order_str = f"#{order.get(m.name, '?')}" if m.name in order else "  "
                print(f"  {CLIRenderer.C_DIM}{order_str}{CLIRenderer.C_RESET} {CLIRenderer.C_CYAN}{m.display_name or m.name}{CLIRenderer.C_RESET} ({m.name}) {CLIRenderer.C_DIM}{m.role}{CLIRenderer.C_RESET}")
        else:
            for m in members:
                print(f"     {CLIRenderer.C_CYAN}{m.display_name or m.name}{CLIRenderer.C_RESET} ({m.name}) {CLIRenderer.C_DIM}{m.role}{CLIRenderer.C_RESET}")
        print()
    
    @staticmethod
    def success(msg: str):
        print(f"  {CLIRenderer.C_GREEN}✅ {msg}{CLIRenderer.C_RESET}")
    
    @staticmethod
    def warning(msg: str):
        print(f"  {CLIRenderer.C_YELLOW}⚠️  {msg}{CLIRenderer.C_RESET}")
    
    @staticmethod
    def error(msg: str):
        print(f"  {CLIRenderer.C_RED}❌ {msg}{CLIRenderer.C_RESET}")
    
    @staticmethod
    def prompt():
        """Display input prompt."""
        return f"{CLIRenderer.C_GREEN}>{CLIRenderer.C_RESET} "
    
    @staticmethod
    def profile_message(display_name: str, profile_name: str, message: str):
        """Display a profile's message."""
        header = f"{CLIRenderer.C_BOLD}{CLIRenderer.C_MAGENTA}[{display_name}]{CLIRenderer.C_RESET}"
        print(f"\n{header}")
        print(f"{CLIRenderer.C_DIM}{'─' * 40}{CLIRenderer.C_RESET}")
        print(message)
        print(f"{CLIRenderer.C_DIM}{'─' * 40}{CLIRenderer.C_RESET}")
    
    @staticmethod
    def thinking(display_name: str):
        """Display thinking indicator."""
        print(f"\n  {CLIRenderer.C_DIM}⏳ {display_name} is thinking...{CLIRenderer.C_RESET}", end="", flush=True)
    
    @staticmethod
    def thinking_done():
        """Clear thinking indicator."""
        print(f"\r{' ' * 60}\r", end="")
