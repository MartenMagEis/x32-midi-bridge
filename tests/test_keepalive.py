import asyncio

import main


def test_keepalive_trips_after_threshold_and_restarts_auto_discovery():
    bridge = main.X32MidiBridge(config={"x32_ip": "auto", "discovery_interval_s": 0.01}, mappings=[])
    bridge.x32_ip = "192.168.1.50"
    bridge.x32_connected = True
    bridge.running = True

    replies = iter([1.0, 1.0, None, None, None])  # 2 ok, then 3 misses -> trips
    query_calls = []

    async def fake_query(path):
        query_calls.append(path)
        return next(replies, None)

    bridge.query_osc_value = fake_query

    discovery_calls = []

    async def fake_auto_discover():
        discovery_calls.append("started")
        await asyncio.sleep(10)  # simulate "still searching", never resolves within the test window

    bridge.auto_discover_x32 = fake_auto_discover

    async def scenario():
        task = asyncio.create_task(bridge.monitor_x32_connection())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.15)
        except asyncio.TimeoutError:
            pass
        bridge.running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    assert len(query_calls) == 5
    assert discovery_calls == ["started"]
    assert bridge.x32_connected is False
    assert bridge.x32_ip is None


def test_keepalive_does_not_retrigger_discovery_every_tick_while_disconnected():
    # Once tripped and rediscovery has been kicked off, subsequent ticks
    # (x32_ip stays None until a real reply arrives) must not repeatedly
    # start new discovery tasks or re-log the warning.
    bridge = main.X32MidiBridge(config={"x32_ip": "auto", "discovery_interval_s": 0.01}, mappings=[])
    bridge.x32_ip = "192.168.1.50"
    bridge.x32_connected = True
    bridge.running = True

    async def fake_query(path):
        return None  # always fails

    bridge.query_osc_value = fake_query

    discovery_calls = []

    async def fake_auto_discover():
        discovery_calls.append("started")
        # Never resolves x32_ip - monitor loop should just keep skipping
        # (x32_ip is None) without calling query_osc_value or discovery again.
        await asyncio.sleep(10)

    bridge.auto_discover_x32 = fake_auto_discover

    async def scenario():
        task = asyncio.create_task(bridge.monitor_x32_connection())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
        except asyncio.TimeoutError:
            pass
        bridge.running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    assert discovery_calls == ["started"]  # exactly once, not once per tick


def test_keepalive_fixed_ip_keeps_retrying_without_clearing_x32_ip():
    bridge = main.X32MidiBridge(config={"x32_ip": "192.168.1.50", "discovery_interval_s": 0.01}, mappings=[])
    bridge.x32_ip = "192.168.1.50"
    bridge.x32_connected = True
    bridge.running = True

    async def fake_query(path):
        return None  # always fails

    bridge.query_osc_value = fake_query

    async def scenario():
        task = asyncio.create_task(bridge.monitor_x32_connection())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
        except asyncio.TimeoutError:
            pass
        bridge.running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    assert bridge.x32_connected is False
    assert bridge.x32_ip == "192.168.1.50"  # fixed IP is never cleared


def test_keepalive_recovers_and_logs_reconnection():
    bridge = main.X32MidiBridge(config={"x32_ip": "192.168.1.50", "discovery_interval_s": 0.01}, mappings=[])
    bridge.x32_ip = "192.168.1.50"
    bridge.x32_connected = False  # starts out already flagged disconnected
    bridge.running = True

    call_count = 0

    async def fake_query(path):
        nonlocal call_count
        call_count += 1
        return 1.0  # always succeeds

    bridge.query_osc_value = fake_query

    async def scenario():
        task = asyncio.create_task(bridge.monitor_x32_connection())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
        except asyncio.TimeoutError:
            pass
        bridge.running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    assert call_count >= 1
    assert bridge.x32_connected is True


def test_keepalive_skips_when_no_ip_known_yet():
    bridge = main.X32MidiBridge(config={"x32_ip": "auto", "discovery_interval_s": 0.01}, mappings=[])
    bridge.x32_ip = None
    bridge.running = True

    async def fake_query(path):
        raise AssertionError("query_osc_value must not be called while x32_ip is None")

    bridge.query_osc_value = fake_query

    async def scenario():
        task = asyncio.create_task(bridge.monitor_x32_connection())
        await asyncio.sleep(0.05)
        bridge.running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())  # would raise via fake_query if the guard were missing
