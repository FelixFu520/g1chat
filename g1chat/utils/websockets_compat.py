"""
websockets 库多版本兼容层

兼容 websockets 13.x (Python 3.8 常用，使用 extra_headers / .closed)
与 websockets 14+/16+ (Python 3.10 常用，使用 additional_headers / .state)。
"""

import websockets


async def ws_connect(url, headers, **kwargs):
    """
    建立 WebSocket 连接，自动适配不同版本的请求头参数名。

    - websockets 14+：使用 additional_headers
    - websockets 13.x：使用 extra_headers

    Args:
        url: WebSocket 服务地址
        headers: 请求头字典（如 X-Api-* 等）
        **kwargs: 其他传给 websockets.connect 的参数（如 max_size, ping_interval）

    Returns:
        WebSocket 连接对象
    """
    try:
        return await websockets.connect(url, additional_headers=headers, **kwargs)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, **kwargs)


def is_ws_connection_closed(conn):
    """
    判断 WebSocket 连接是否已关闭，兼容 13.x 与 14+。

    - websockets 13.x：使用 connection.closed
    - websockets 14+：使用 connection.state is State.CLOSED（无 .closed 属性）

    Args:
        conn: WebSocket 连接对象或 None

    Returns:
        True 表示无需使用（conn 为 None）或连接已关闭，False 表示连接仍打开。
    """
    if conn is None:
        return True
    if hasattr(conn, "closed"):
        return conn.closed
    try:
        from websockets.protocol import State
        return getattr(conn, "state", None) is State.CLOSED
    except Exception:
        return True
