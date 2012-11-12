
import gevent

def schedule(duration, func, *args, **kwargs):
    gevent.spawn_later(duration, schedule, duration, func, *args, **kwargs)
    gevent.spawn_later(0, func, *args, **kwargs)
