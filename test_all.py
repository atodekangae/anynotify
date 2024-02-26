from unittest.mock import patch, MagicMock
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

def test_sync():
    import anynotify
    import logging

    with anynotify.init(
            worker_cls=anynotify.SyncWorker,
            client=anynotify.DiscordClient('https://localhost/webhook'),
            integrations=[anynotify.LoggingIntegration()]) as hub:
        with patch('requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_post.return_value = mock_response
            logging.info('test')
            logging.warning('test')
            assert mock_post.call_count == 1

@pytest.mark.parametrize('kind', ['gevent', 'thread'])
def test_async(kind):
    import anynotify
    import logging
    import time
    if kind == 'gevent':
        import gevent
        sleep = gevent.sleep
        spawn = gevent.spawn
        worker_cls = anynotify.GeventWorker
    elif kind == 'thread':
        import threading
        sleep = time.sleep
        def spawn(target, *args):
            t = threading.Thread(target=target, args=args)
            t.start()
            return t
        worker_cls = anynotify.ThreadWorker
    else:
        raise ValueError()

    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response
        started = time.monotonic()
        with anynotify.init(
            worker_cls=worker_cls,
            client=anynotify.DiscordClient('http://localhost/webhook', anynotify.RateLimiter(60, 10, 0.1)),
            integrations=[anynotify.LoggingIntegration()]) as hub:

            logging.info('test')
            logging.warning('test 1')
            logging.error('test 2')
            logging.critical('test 3')
            try:
                1/0
            except:
                logging.exception('test 4')
        elapsed = time.monotonic() - started
        assert mock_post.call_count == 4
        assert elapsed > 0.1 * 3

    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response
        started = time.monotonic()
        with anynotify.init(
            worker_cls=worker_cls,
            client=anynotify.DiscordClient('http://localhost/webhook', anynotify.RateLimiter(60, 10, 0)),
            integrations=[anynotify.LoggingIntegration()]) as hub:

            logging.info('test')
            def f(n):
                hub.push_context(x=n)
                sleep((3-n)/10)
                logging.warning('test %d', n)
            gs = []
            for i in range(3):
                gs.append(spawn(f, i))
            for g in gs:
                g.join()
        elapsed = time.monotonic() - started
        e = mock_post.call_args_list[0].kwargs['json']['embeds'][0]
        assert 'test 2' in e['title'] and "'x': 2" in e['description']
        e = mock_post.call_args_list[1].kwargs['json']['embeds'][0]
        assert 'test 1' in e['title'] and "'x': 1" in e['description']
        e = mock_post.call_args_list[2].kwargs['json']['embeds'][0]
        assert 'test 0' in e['title'] and "'x': 0" in e['description']
        assert mock_post.call_count == 3

def test_ratelimit():
    import anynotify
    rl = anynotify.RateLimiter(last_n_seconds=10, max_requests=3)
    assert rl.get_wait_duration(1) is None
    rl.inc(1)
    assert rl.get_wait_duration(2) is None
    rl.inc(2)
    assert rl.get_wait_duration(4) is None
    rl.inc(4)
    d = rl.get_wait_duration(4)
    assert d is not None
    assert d == 7
    assert rl.get_wait_duration(11-0.001) > 0
    assert rl.get_wait_duration(11+0.001) is None

    rl = anynotify.RateLimiter(last_n_seconds=10, max_requests=3, min_interval=1)
    assert rl.get_wait_duration(1) is None
    rl.inc(1)
    assert rl.get_wait_duration(2-0.001) > 0
    assert rl.get_wait_duration(2) is None
    rl.inc(2)

    rl = anynotify.RateLimiter(last_n_seconds=10, max_requests=3, min_interval=3)
    rl.inc(1)
    assert rl.get_wait_duration(1) == 3
