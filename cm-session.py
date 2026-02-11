#!/usr/bin/env python3
"""
CM Session Manager - 管理 coding sessions
"""

import json
import os
import subprocess
import time
from typing import Optional, Dict
from datetime import datetime
import sys
import asyncio

# 添加路径
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# 动态导入
import importlib.util

def load_module(name, path):
    """动态加载模块"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# 加载依赖模块
cm_context = load_module("cm_context", os.path.join(script_dir, "cm-context.py"))
Context = cm_context.Context


class Session:
    """代表一个 coding session"""
    
    def __init__(self, data: dict):
        self.id = data['id']
        self.context_id = data.get('contextId')
        self.tool = data['tool']
        self.task = data['task']
        self.status = data.get('status', 'pending')
        self.state = data.get('state', 'starting')
        self.started = data.get('started')
        self.completed = data.get('completed')
        self.mode = data.get('mode', 'local')  # local, ssh, agent
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'contextId': self.context_id,
            'tool': self.tool,
            'task': self.task,
            'status': self.status,
            'state': self.state,
            'started': self.started,
            'completed': self.completed,
            'mode': self.mode
        }


class SessionManager:
    """Session 管理器"""
    
    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or os.path.expanduser('~/.cm')
        self.sessions_dir = os.path.join(self.data_dir, 'sessions', 'active')
        self.history_dir = os.path.join(self.data_dir, 'history')
        
        # 确保目录存在
        os.makedirs(self.sessions_dir, exist_ok=True)
        os.makedirs(self.history_dir, exist_ok=True)
    
    def create_session(self, tool: str, task: str, context: Context) -> Session:
        """创建新 session"""
        # 生成 ID
        session_id = f"sess-{int(time.time())}"
        
        # 确定模式
        if context.is_agent():
            mode = 'agent'
        elif context.is_remote():
            mode = 'ssh'
        else:
            mode = 'local'
        
        # 创建 session
        data = {
            'id': session_id,
            'contextId': context.id,
            'tool': tool,
            'task': task,
            'status': 'pending',
            'state': 'starting',
            'started': datetime.now().isoformat(),
            'mode': mode
        }
        
        session = Session(data)
        
        # 保存
        self._save_session(session)
        
        return session
    
    def _save_session(self, session: Session):
        """保存 session"""
        session_file = os.path.join(self.sessions_dir, f"{session.id}.json")
        with open(session_file, 'w') as f:
            json.dump(session.to_dict(), f, indent=2)
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """获取 session"""
        session_file = os.path.join(self.sessions_dir, f"{session_id}.json")
        if not os.path.exists(session_file):
            return None
        
        with open(session_file, 'r') as f:
            data = json.load(f)
        
        return Session(data)
    
    def list_sessions(self) -> list:
        """列出所有 active sessions"""
        sessions = []
        
        if not os.path.exists(self.sessions_dir):
            return sessions
        
        for filename in os.listdir(self.sessions_dir):
            if filename.endswith('.json'):
                with open(os.path.join(self.sessions_dir, filename), 'r') as f:
                    data = json.load(f)
                    sessions.append(Session(data))
        
        return sessions
    
    def start_local(self, session: Session, context: Context) -> bool:
        """启动本地 session"""
        print(f"   Mode: Local TMUX")
        print(f"   Executor: cm-executor-tmux.sh")
        
        # 准备 session 文件
        self._save_session(session)
        
        # 调用 executor
        executor = os.path.join(script_dir, 'cm-executor-tmux.sh')
        
        if not os.path.exists(executor):
            print(f"❌ Executor not found: {executor}")
            return False
        
        # 启动（后台）
        cmd = [executor, session.id]
        
        try:
            # 使用 subprocess 启动后台进程
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=context.path
            )
            
            print(f"✅ Session started: {session.id}")
            print(f"   PID: {process.pid}")
            print(f"   Path: {context.path}")
            print(f"   Tool: {session.tool}")
            
            return True
        
        except Exception as e:
            print(f"❌ Failed to start: {e}")
            return False
    
    def start_agent(self, session: Session, context: Context) -> bool:
        """启动 Agent session"""
        print(f"   Mode: Agent Server (Remote)")
        print(f"   Host: {context.machine.get('host')}")
        
        try:
            # 导入 Manager Client
            manager_client_path = os.path.join(script_dir, 'cm-manager-client.py')
            cm_manager = load_module("cm_manager_client", manager_client_path)
            CMManagerClient = cm_manager.CMManagerClient
            
            # 异步启动
            async def start():
                client = CMManagerClient(
                    host=context.machine['host'],
                    user=context.machine['user'],
                    auth_token=context.machine.get('authToken'),
                    agent_port=context.machine.get('agentPort', 9876)
                )
                
                print(f"   Connecting to Agent...")
                if not await client.connect():
                    print(f"❌ Connection failed")
                    return False
                
                print(f"✅ Connected")
                
                # 创建远程 session
                print(f"   Creating remote session...")
                remote_session_id = await client.create_session(
                    tool=session.tool,
                    task=session.task,
                    context={'path': context.path}
                )
                
                print(f"✅ Session started: {remote_session_id}")
                print(f"   Local ID: {session.id}")
                print(f"   Remote ID: {remote_session_id}")
                
                # 更新 session
                session.status = 'running'
                self._save_session(session)
                
                # 保持连接（后台监控）
                print(f"   Monitoring in background...")
                print(f"   Use 'cm status {session.id}' to check progress")
                
                # TODO: 在后台持续监控
                # 现在先断开
                await client.disconnect()
                
                return True
            
            # 运行异步任务
            result = asyncio.run(start())
            return result
        
        except Exception as e:
            print(f"❌ Failed to start Agent session: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def start_ssh(self, session: Session, context: Context) -> bool:
        """启动 SSH session"""
        print(f"   Mode: SSH (Remote)")
        print(f"   ⚠️  SSH mode not fully implemented yet")
        print(f"   Use Agent mode for remote execution")
        return False


def main():
    """测试"""
    print("=" * 60)
    print("CM Session Manager - Test")
    print("=" * 60)
    print()
    
    mgr = SessionManager()
    
    # 创建测试 context
    ContextManager = cm_context.ContextManager
    ctx_mgr = ContextManager()
    
    # 获取或创建 local context
    ctx = ctx_mgr.get('local-test')
    if not ctx:
        ctx = ctx_mgr.add('local-test', '/home/hren/.openclaw/workspace', 'local')
    
    # 创建 session
    print("Creating test session...")
    session = mgr.create_session(
        tool='claude',
        task='Create test file from session manager',
        context=ctx
    )
    
    print(f"✅ Session created: {session.id}")
    print(f"   Mode: {session.mode}")
    print()
    
    # 列出 sessions
    print("Active sessions:")
    for s in mgr.list_sessions():
        print(f"   - {s.id}: {s.tool} ({s.mode})")
    print()
    
    print("=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
