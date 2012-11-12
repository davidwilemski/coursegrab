
import gevent

def schedule(duration, func, *args, **kwargs):
    func(*args, **kwargs)
    gevent.spawn_later(duration, schedule, duration, func, *args, **kwargs).join()
