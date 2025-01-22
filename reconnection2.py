# encoding:utf-8

import json
import os
import time
import logging
from common.log import logger
from plugins import Plugin
import plugins
from config import conf
from plugins import Event, EventContext, EventAction
import threading
from datetime import datetime, timedelta
from bridge.bridge import Bridge
from lib.gewechat import GewechatClient
from lib.gewechat.api.login_api import LoginApi
from plugins.plugin_manager import PluginManager
import re
import requests

'''为LoginApi增加断线重连方法'''
class LoginApi_ex(LoginApi):
    def __init__(self, base_url, token):
        # 调用父类构造函数，继承父类属性
        super().__init__(base_url, token)

    def reconnection(self, app_id):
        """断线重连"""
        param = {
            "appId": app_id
        }
        return post_json(self.base_url, "/login/reconnection", self.token, param)

'''为GewechatClient增加断线重连方法'''
class GewechatClient_ex(GewechatClient):
    def __init__(self, base_url, token):
        # 调用父类构造函数，继承父类属性
        super().__init__(base_url, token)
        # 修改属性为新定义的LoginApi_ex
        self._login_api = LoginApi_ex(base_url, token)
        
    def reconnection(self, app_id):
        """断线重连"""
        return self._login_api.reconnection(app_id)

@plugins.register(
    name="Reconnection",
    desire_priority=950,
    hidden=False,
    desc="断线重连",
    version="0.0.2",
    author="fone",
)
class Reconnection(Plugin):
    # 添加类变量来跟踪实例和初始化状态
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # 初始化类变量
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # 确保只初始化一次
        if not self._initialized:
            super().__init__()
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            # 初始化客户端
            self.client = GewechatClient(conf().get("gewechat_base_url"), conf().get("gewechat_token"))
            self.app_id = conf().get("gewechat_app_id")
            # 测试重连接口
            self.test_reconnection_api()
            # 启动定时器
            self.running = True
            self.timer_thread = threading.Thread(target=self._timer_loop)
            self.timer_thread.daemon = True
            self.timer_thread.start()
            logger.info("[Reconnection] inited")
            self._initialized = True


    def __del__(self):
        """析构函数，确保线程正确退出"""
        self.running = False
        if hasattr(self, 'timer_thread') and self.timer_thread.is_alive():
            self.timer_thread.join(timeout=1)
            logger.info("[Reconnection] timer thread stopped")

    def checkOnline(self):
        """检查设备是否在线"""
        try:
            # 检查在线
            result = self.client.check_online(
                conf().get("gewechat_app_id")
            )
            return result['data']
        except Exception as e:
            logger.error(f"[Reconnection] 检查设备是否在线失败: {e}")

    def reconnection(self):
        """断线重连"""
        try:
            result = self.client.reconnection(
                conf().get("gewechat_app_id")
            )
            logger.info(f"[Reconnection] {result.get('msg')}")
        except Exception as e:
            logger.error(f"[Reconnection] 设备重连失败: {e}")

    def test_reconnection_api(self):
        """测试重连接口"""
        try:
            result = self.client.reconnection(
                conf().get("gewechat_app_id")
            )
            if result.get('ret') == 200:
                logger.info(f"[Reconnection] 重连成功")
        except Exception as e:
            if "无需重连" in str(e):
                logger.info(f"[Reconnection] 重连接口正常")
            else:
                logger.error(f"[Reconnection] 重连接口异常: {e}")                

    def _timer_loop(self):
        """定时器循环"""
        last_execute_time = 0  # 记录上次执行任务的时间
        
        while self.running:
            try:
                now = datetime.now()
                current_time = int(time.time())
                
                # 检查设备是否在线
                try:
                    # 检查是否在线
                    is_on = self.checkOnline()
                    if is_on == True:
                        # 获取当前小时的整点时间
                        current_whole_hour = now.replace(minute=0, second=0, microsecond=0)
                        # 当前的整点时间超过上次执行任务的时间
                        if int(current_whole_hour.timestamp()) > last_execute_time:
                            logger.info(f"[Reconnection] 设备在线")
                    elif is_on == False:
                        logger.info(f"[Reconnection] 设备不在线，尝试重连")
                        self.reconnection()
                    last_execute_time = int(time.time())  # 更新最后执行时间
                except Exception as e:
                    logger.error(f"[Reconnection] 检查在线 任务异常: {str(e)}")
                
                # 每一分钟检查一次
                sleep_time = 60 - datetime.now().second
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"[Reconnection] 定时器异常: {e}")
                time.sleep(60)

    def emit_event(self, event: Event, e_context: EventContext = None):
        """触发事件"""
        try:
            # 获取插件管理器
            plugin_manager = PluginManager()
            # 触发事件
            plugin_manager.emit_event(event, e_context)
        except Exception as e:
            logger.error(f"[Reconnection] 触发事件失败: {e}")
            
    def on_handle_context(self, e_context: EventContext):
        return