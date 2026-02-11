#!/usr/bin/env python3
"""
CM - Code Manager CLI
统一的命令行接口，支持本地和远程执行
"""

import sys
import os
import argparse
from typing import Optional
import importlib.util

# 添加当前目录到路径
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# 动态导入 cm_context
spec = importlib.util.spec_from_file_location("cm_context", os.path.join(script_dir, "cm-context.py"))
cm_context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm_context)

ContextManager = cm_context.ContextManager
Context = cm_context.Context


def cmd_ctx_add(args):
    """添加 context"""
    mgr = ContextManager()
    
    # 构建 machine 配置
    if args.agent:
        # Agent Server 模式
        machine = {
            'type': 'agent',
            'host': args.host or input("Agent host: "),
            'user': args.user or input("SSH user: "),
            'agentPort': args.agent_port,
            'authToken': args.token or input("Auth token: ")
        }
    elif args.host:
        # SSH 模式
        machine = {
            'type': 'ssh',
            'host': args.host,
            'user': args.user or os.environ.get('USER'),
            'port': args.port,
            'keyFile': args.key
        }
    else:
        # 本地模式
        machine = 'local'
    
    # 添加 context
    ctx = mgr.add(
        name=args.name,
        path=args.path,
        machine=machine,
        tags=args.tags.split(',') if args.tags else []
    )
    
    print(f"✅ Context added: {ctx.get_display_name()}")
    print(f"   ID: {ctx.id}")
    print(f"   Path: {ctx.path}")
    print(f"   Type: {'Agent' if ctx.is_agent() else ('SSH' if ctx.is_remote() else 'Local')}")


def cmd_ctx_list(args):
    """列出 contexts"""
    mgr = ContextManager()
    contexts = mgr.list()
    
    if not contexts:
        print("No contexts found.")
        print("Add one with: cm ctx add <name> <path>")
        return
    
    # 表头
    print(f"{'ID':<12} {'Name':<20} {'Type':<10} {'Machine':<30} {'Path':<30}")
    print("-" * 102)
    
    # 列出
    for ctx in contexts:
        if ctx.is_agent():
            type_str = "agent"
            machine_info = ctx.machine.get('host', 'unknown')
        elif ctx.is_remote():
            type_str = "ssh"
            if isinstance(ctx.machine, dict):
                user = ctx.machine.get('user', '')
                host = ctx.machine.get('host', '')
                machine_info = f"{user}@{host}" if user else host
            else:
                machine_info = str(ctx.machine)
        else:
            type_str = "local"
            machine_info = "-"
        
        print(f"{ctx.id:<12} {ctx.name:<20} {type_str:<10} {machine_info:<30} {ctx.path:<30}")


def cmd_ctx_show(args):
    """显示 context 详情"""
    mgr = ContextManager()
    ctx = mgr.get(args.name)
    
    if not ctx:
        print(f"❌ Context not found: {args.name}")
        return
    
    print(f"Context: {ctx.get_display_name()}")
    print(f"  ID: {ctx.id}")
    print(f"  Path: {ctx.path}")
    print(f"  Tags: {', '.join(ctx.tags) if ctx.tags else 'none'}")
    print(f"  Created: {ctx.created}")
    print(f"  Last used: {ctx.last_used or 'never'}")
    
    if ctx.is_remote():
        print(f"  Machine:")
        if isinstance(ctx.machine, dict):
            for key, value in ctx.machine.items():
                if key != 'authToken':  # 隐藏 token
                    print(f"    {key}: {value}")
        else:
            print(f"    {ctx.machine}")


def cmd_ctx_test(args):
    """测试 context 连接"""
    mgr = ContextManager()
    ctx = mgr.get(args.name)
    
    if not ctx:
        print(f"❌ Context not found: {args.name}")
        return
    
    print(f"Testing connection to: {ctx.get_display_name()}")
    success, msg = ctx.test_connection()
    
    if success:
        print(f"✅ {msg}")
    else:
        print(f"❌ {msg}")


def cmd_ctx_remove(args):
    """删除 context"""
    mgr = ContextManager()
    
    if mgr.remove(args.name):
        print(f"✅ Context removed: {args.name}")
    else:
        print(f"❌ Context not found: {args.name}")


def cmd_start(args):
    """启动编码任务"""
    # 加载模块
    cm_session = load_module("cm_session", os.path.join(script_dir, "cm-session.py"))
    SessionManager = cm_session.SessionManager
    
    mgr_ctx = ContextManager()
    mgr_sess = SessionManager()
    
    # 获取 context
    ctx = mgr_ctx.get(args.ctx) if args.ctx else None
    
    if args.ctx and not ctx:
        print(f"❌ Context not found: {args.ctx}")
        return
    
    # 使用当前目录作为默认 context
    if not ctx:
        ctx = Context({
            'id': 'temp',
            'name': 'current-dir',
            'path': os.getcwd(),
            'machine': 'local'
        })
    
    # 显示信息
    print(f"🚀 Starting {args.tool} session...")
    print(f"   Context: {ctx.get_display_name()}")
    print(f"   Path: {ctx.path}")
    print(f"   Task: {args.task}")
    print()
    
    # 创建 session
    session = mgr_sess.create_session(args.tool, args.task, ctx)
    
    # 根据模式启动
    if ctx.is_agent():
        success = mgr_sess.start_agent(session, ctx)
    elif ctx.is_remote():
        success = mgr_sess.start_ssh(session, ctx)
    else:
        success = mgr_sess.start_local(session, ctx)
    
    if success:
        print()
        print(f"📝 Session Info:")
        print(f"   ID: {session.id}")
        print(f"   Mode: {session.mode}")
        print(f"   Status: {session.status}")
        print()
        print(f"💡 Check status: python3 cm-cli.py status {session.id}")
    else:
        print()
        print(f"❌ Failed to start session")


def cmd_status(args):
    """显示 session 状态"""
    # 加载模块
    cm_session = load_module("cm_session", os.path.join(script_dir, "cm-session.py"))
    SessionManager = cm_session.SessionManager
    
    mgr = SessionManager()
    
    if args.session_id:
        # 显示特定 session
        session = mgr.get_session(args.session_id)
        
        if not session:
            print(f"❌ Session not found: {args.session_id}")
            return
        
        print(f"Session: {session.id}")
        print(f"  Tool: {session.tool}")
        print(f"  Task: {session.task}")
        print(f"  Mode: {session.mode}")
        print(f"  Status: {session.status}")
        print(f"  State: {session.state}")
        print(f"  Started: {session.started}")
        if session.completed:
            print(f"  Completed: {session.completed}")
    
    else:
        # 列出所有 sessions
        sessions = mgr.list_sessions()
        
        if not sessions:
            print("No active sessions")
            return
        
        print(f"Active Sessions: {len(sessions)}")
        print()
        print(f"{'ID':<20} {'Tool':<10} {'Mode':<10} {'Status':<12} {'State':<12}")
        print("-" * 74)
        
        for s in sessions:
            print(f"{s.id:<20} {s.tool:<10} {s.mode:<10} {s.status:<12} {s.state:<12}")


def cmd_logs(args):
    """查看 session 日志"""
    log_file = os.path.expanduser(f'~/.cm/sessions/active/{args.session_id}.log')
    
    if not os.path.exists(log_file):
        print(f"❌ No log file for session: {args.session_id}")
        return
    
    # 使用 cm-logs.py
    cm_logs = os.path.join(script_dir, 'cm-logs.py')
    cmd = ['python3', cm_logs, args.session_id, '-n', str(args.lines)]
    
    if args.follow:
        cmd.append('-f')
    
    import subprocess
    subprocess.run(cmd)


def cmd_kill(args):
    """终止 session"""
    # 加载模块
    cm_session = load_module("cm_session", os.path.join(script_dir, "cm-session.py"))
    SessionManager = cm_session.SessionManager
    
    mgr = SessionManager()
    session = mgr.get_session(args.session_id)
    
    if not session:
        print(f"❌ Session not found: {args.session_id}")
        return
    
    print(f"🛑 Killing session: {session.id}")
    print(f"   Tool: {session.tool}")
    print(f"   Mode: {session.mode}")
    
    # 根据模式终止
    if session.mode == 'local':
        # 查找并终止 TMUX session
        socket = f"/tmp/cm-tmux-sockets/{session.id}.sock"
        cmd = f"tmux -S {socket} kill-session -t {session.id} 2>/dev/null"
        
        import subprocess
        result = subprocess.run(cmd, shell=True)
        
        if result.returncode == 0:
            print(f"✅ TMUX session killed")
        else:
            print(f"⚠️  TMUX session may not exist")
    
    elif session.mode == 'agent':
        print(f"⚠️  Agent session kill not fully implemented")
        print(f"   Use Agent Server to kill remote session")
    
    else:
        print(f"⚠️  SSH session kill not fully implemented")
    
    # 删除 session 文件
    session_file = os.path.expanduser(f'~/.cm/sessions/active/{session.id}.json')
    if os.path.exists(session_file):
        os.remove(session_file)
        print(f"✅ Session file removed")
    
    print(f"✅ Session {session.id} killed")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='CM - Code Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add contexts
  cm ctx add local-proj /path/to/project
  cm ctx add remote-proj /var/www/app --host server.com --user deploy
  cm ctx add agent-proj /home/user/app --agent --host agent.com --token xxx
  
  # List contexts
  cm ctx list
  
  # Start tasks
  cm start claude "Add logging" --ctx remote-proj
  cm start codex "Fix bug" --ctx local-proj
  
  # Status
  cm status
  cm status session-id
"""
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    # ctx 命令组
    ctx_parser = subparsers.add_parser('ctx', help='Manage contexts')
    ctx_sub = ctx_parser.add_subparsers(dest='ctx_command')
    
    # ctx add
    add_parser = ctx_sub.add_parser('add', help='Add context')
    add_parser.add_argument('name', help='Context name')
    add_parser.add_argument('path', help='Project path')
    add_parser.add_argument('--host', help='Remote host')
    add_parser.add_argument('--user', help='SSH user')
    add_parser.add_argument('--port', type=int, default=22, help='SSH port')
    add_parser.add_argument('--key', help='SSH key file')
    add_parser.add_argument('--agent', action='store_true', help='Use Agent Server')
    add_parser.add_argument('--agent-port', type=int, default=9876, help='Agent port')
    add_parser.add_argument('--token', help='Agent auth token')
    add_parser.add_argument('--tags', help='Tags (comma-separated)')
    add_parser.set_defaults(func=cmd_ctx_add)
    
    # ctx list
    list_parser = ctx_sub.add_parser('list', help='List contexts')
    list_parser.set_defaults(func=cmd_ctx_list)
    
    # ctx show
    show_parser = ctx_sub.add_parser('show', help='Show context details')
    show_parser.add_argument('name', help='Context name or ID')
    show_parser.set_defaults(func=cmd_ctx_show)
    
    # ctx test
    test_parser = ctx_sub.add_parser('test', help='Test connection')
    test_parser.add_argument('name', help='Context name or ID')
    test_parser.set_defaults(func=cmd_ctx_test)
    
    # ctx remove
    remove_parser = ctx_sub.add_parser('remove', help='Remove context')
    remove_parser.add_argument('name', help='Context name or ID')
    remove_parser.set_defaults(func=cmd_ctx_remove)
    
    # start 命令
    start_parser = subparsers.add_parser('start', help='Start coding session')
    start_parser.add_argument('tool', choices=['claude', 'codex', 'cursor'], help='Coding tool')
    start_parser.add_argument('task', help='Task description')
    start_parser.add_argument('--ctx', help='Context name or ID')
    start_parser.set_defaults(func=cmd_start)
    
    # logs 命令
    logs_parser = subparsers.add_parser('logs', help='View session logs')
    logs_parser.add_argument('session_id', help='Session ID')
    logs_parser.add_argument('-f', '--follow', action='store_true', help='Follow log output')
    logs_parser.add_argument('-n', '--lines', type=int, default=50, help='Number of lines')
    logs_parser.set_defaults(func=cmd_logs)
    
    # kill 命令
    kill_parser = subparsers.add_parser('kill', help='Kill session')
    kill_parser.add_argument('session_id', help='Session ID')
    kill_parser.set_defaults(func=cmd_kill)
    
    # 解析参数
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # 执行命令
    if hasattr(args, 'func'):
        args.func(args)
    else:
        print(f"Unknown command: {args.command}")
        parser.print_help()


if __name__ == '__main__':
    main()
