"""
天勤数据服务模块
"""

from datetime import timedelta, datetime
from collections.abc import Callable
import traceback
from pandas import DataFrame

from vnpy.trader.datafeed import BaseDatafeed
from vnpy.trader.object import HistoryRequest, BarData, TickData
from vnpy.trader.constant import Interval
from vnpy.trader.utility import ZoneInfo

INTERVAL_VT2TQ: dict[Interval, int] = {
    Interval.MINUTE: 60,
    Interval.MINUTE_5: 300,
    Interval.MINUTE_15: 900,
    Interval.MINUTE_30: 1800,
    Interval.HOUR: 60 * 60,
    Interval.HOUR_2: 60 * 60 * 2,
    Interval.HOUR_4: 60 * 60 * 4,
    Interval.DAILY: 60 * 60 * 24,
    Interval.WEEKLY: 60 * 60 * 24 * 7,
    Interval.MONTHLY: 60 * 60 * 24 * 30
}

CHINA_TZ = ZoneInfo("Asia/Shanghai")


class TqSdkDatafeed(BaseDatafeed):
    """
    天勤数据服务类，用于查询历史行情数据
    """

    def __init__(self) -> None:
        """
        初始化
        """
        self.api = None
        self.inited = False

    def init(self, output: Callable = print) -> bool:
        """
        初始化数据服务连接
        """
        try:
            from tqsdk import TqApi, TqAuth
            from vnpy.trader.setting import SETTINGS
            
            # 从配置中获取用户名和密码
            username: str = SETTINGS.get("datafeed.username", "")
            password: str = SETTINGS.get("datafeed.password", "")
            
            # 创建天勤API实例
            try:
                if username and password:
                    # 尝试使用配置的用户名和密码
                    self.api = TqApi(auth=TqAuth(username, password))
                else:
                    # 使用模拟账户
                    self.api = TqApi()
            except Exception as auth_e:
                # 如果认证失败，降级使用模拟账户
                output(f"使用配置的用户名和密码认证失败: {str(auth_e)}")
                output("降级使用模拟账户连接天勤API")
                self.api = TqApi()
            
            self.inited = True
            
            output("天勤数据服务连接成功")
            return True
        except Exception as e:
            output(f"天勤数据服务连接失败: {str(e)}")
            return False

    def query_bar_history(self, req: HistoryRequest, output: Callable = print) -> list[BarData] | None:
        """
        查询历史K线数据
        """
        if not self.inited:
            output("天勤数据服务未初始化")
            return None

        try:
            # 转换时间间隔
            interval: int | None = INTERVAL_VT2TQ.get(req.interval, None)
            if not interval:
                output(f"Tqsdk查询K线数据失败：不支持的时间周期{req.interval.value}")
                return None

            # 构建合约代码
            vt_symbol: str = f"{req.exchange.value}.{req.symbol}"
            output(f"查询K线数据: {vt_symbol} - {req.interval.value}")

            # 使用get_kline_data_series获取K线数据
            df = self.api.get_kline_data_series(
                symbol=vt_symbol,
                duration_seconds=interval,
                start_dt=req.start,
                end_dt=req.end
            )

            # 解析数据
            bars: list[BarData] = []

            if not df.empty:
                output(f"成功获取 {len(df)} 条{req.interval.value}数据")
                
                for tp in df.itertuples():
                    # 转换datetime（纳秒数）为datetime对象
                    dt = datetime.fromtimestamp(getattr(tp, "datetime") / 1_000_000_000, tz=CHINA_TZ)
                    
                    # 创建BarData对象
                    bar: BarData = BarData(
                        symbol=req.symbol,
                        exchange=req.exchange,
                        interval=req.interval,
                        datetime=dt,
                        open_price=tp.open,
                        high_price=tp.high,
                        low_price=tp.low,
                        close_price=tp.close,
                        volume=tp.volume,
                        open_interest=getattr(tp, "open_oi", 0),
                        gateway_name="TQ"
                    )
                    bars.append(bar)

            return bars
        except Exception as e:
            error_msg = str(e)
            if "权限" in error_msg or "403" in error_msg:
                output("获取K线数据需要专业版权限")
                output("如果您有专业版权限，请确保账号密码正确")
            elif "请输入 auth" in error_msg:
                output("天勤API需要账号认证")
                output("请在vt_setting.json中配置正确的天勤账号和密码")
            else:
                output(f"查询K线数据失败: {error_msg}")
            return []

    def is_valid_price(self, price):
        """
        检查价格是否有效（非None、非NaN、>0）
        """
        try:
            # 先检查是否为None
            if price is None:
                return False
            
            # 尝试转换为浮点数
            float_price = float(price)
            
            # 检查是否为NaN或无穷大
            import numpy as np
            if np.isnan(float_price) or np.isinf(float_price):
                return False
            
            # 检查是否大于0
            return float_price > 0.0
        except (ImportError, ValueError, TypeError):
            # 如果转换失败或numpy不可用，使用简单检查
            try:
                return float(price) > 0.0
            except (ValueError, TypeError):
                return False

    def query_tick_history(self, req: HistoryRequest, output: Callable = print) -> list[TickData] | None:
        """
        查询历史Tick数据
        """
        if not self.inited:
            output("天勤数据服务未初始化")
            return None

        try:
            # 构建合约代码
            vt_symbol: str = f"{req.exchange.value}.{req.symbol}"
            output(f"查询Tick数据: {vt_symbol}")

            # 使用get_tick_data_series获取历史Tick数据
            df = self.api.get_tick_data_series(
                symbol=vt_symbol,
                start_dt=req.start,
                end_dt=req.end
            )
            
            # 解析数据
            ticks: list[TickData] = []
            
            if not df.empty:
                output(f"成功获取 {len(df)} 条Tick数据")
                
                for tp in df.itertuples():
                    # 转换datetime（纳秒数）为datetime对象
                    dt = datetime.fromtimestamp(getattr(tp, "datetime") / 1_000_000_000, tz=CHINA_TZ)
                    
                    # 获取并验证所有价格字段
                    last_price = getattr(tp, "last_price", None)
                    highest = getattr(tp, "highest", None)
                    lowest = getattr(tp, "lowest", None)
                    # 尝试其他可能的字段名
                    highest = highest or getattr(tp, "high", None)
                    lowest = lowest or getattr(tp, "low", None)
                    bid_price1 = getattr(tp, "bid_price1", None)
                    ask_price1 = getattr(tp, "ask_price1", None)
                    
                    # 先收集所有可能的有效价格用于 fallback
                    available_prices = []
                    for price in [last_price, bid_price1, ask_price1, highest, lowest]:
                        if self.is_valid_price(price):
                            available_prices.append(price)
                    
                    # 验证last_price，如果无效则尝试使用其他价格
                    if not self.is_valid_price(last_price):
                        # 尝试使用买一价或卖一价
                        if self.is_valid_price(bid_price1):
                            last_price = bid_price1
                        elif self.is_valid_price(ask_price1):
                            last_price = ask_price1
                        elif available_prices:
                            # 尝试使用任何可用的有效价格
                            last_price = available_prices[0]
                        else:
                            # 如果都无效，跳过这条记录
                            continue
                    
                    # 验证high_price，如果无效则使用last_price或其他可用价格
                    if not self.is_valid_price(highest):
                        if available_prices:
                            highest = max(available_prices)
                        else:
                            highest = last_price
                    
                    # 验证low_price，如果无效则使用last_price或其他可用价格
                    if not self.is_valid_price(lowest):
                        if available_prices:
                            lowest = min(available_prices)
                        else:
                            lowest = last_price
                    
                    # 确保high_price和low_price至少为0.0
                    highest = highest if self.is_valid_price(highest) else 0.0
                    lowest = lowest if self.is_valid_price(lowest) else 0.0
                    
                    # 验证bid_price1，如果无效则使用0
                    bid_price1 = bid_price1 if self.is_valid_price(bid_price1) else 0.0
                    
                    # 验证ask_price1，如果无效则使用0
                    ask_price1 = ask_price1 if self.is_valid_price(ask_price1) else 0.0
                    
                    # 创建TickData对象
                    tick: TickData = TickData(
                        symbol=req.symbol,
                        exchange=req.exchange,
                        datetime=dt,
                        name="",
                        volume=getattr(tp, "volume", 0),
                        turnover=getattr(tp, "amount", 0),
                        open_interest=getattr(tp, "open_interest", 0),
                        last_price=last_price,
                        limit_up=0.0,
                        limit_down=0.0,
                        open_price=0.0,
                        high_price=highest,
                        low_price=lowest,
                        pre_close=0.0,
                        bid_price_1=bid_price1,
                        ask_price_1=ask_price1,
                        bid_volume_1=getattr(tp, "bid_volume1", 0),
                        ask_volume_1=getattr(tp, "ask_volume1", 0),
                        bid_price_2=0.0,
                        bid_volume_2=0,
                        ask_price_2=0.0,
                        ask_volume_2=0,
                        bid_price_3=0.0,
                        bid_volume_3=0,
                        ask_price_3=0.0,
                        ask_volume_3=0,
                        gateway_name="TQ"
                    )
                    ticks.append(tick)
            else:
                output("未获取到Tick数据")
                return []
            
            return ticks
        except Exception as e:
            error_msg = str(e)
            if "权限" in error_msg or "403" in error_msg:
                output("获取Tick数据需要专业版权限，回测推荐使用K线数据")
                output("如果您有专业版权限，请确保账号密码正确")
            elif "请输入 auth" in error_msg:
                output("天勤API需要账号认证")
                output("请在vt_setting.json中配置正确的天勤账号和密码")
            else:
                output(f"查询Tick数据失败: {error_msg}")
            return []

    def close(self):
        """
        关闭数据服务连接
        """
        if self.api:
            self.api.close()
            self.api = None
            self.inited = False


# 创建数据服务对象
Datafeed = TqSdkDatafeed
