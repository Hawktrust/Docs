"""Gunicorn configuration.

Logging goes to stdout and stderr so the journal has it. A log file the
application rotates itself is a log file nobody reads.
"""
import multiprocessing

bind = "127.0.0.1:8000"          # nginx terminates TLS in front
workers = max(2, multiprocessing.cpu_count())
worker_class = "sync"            # the app is database-bound, not IO-concurrent
timeout = 30
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = "info"

# Without this every request logs 127.0.0.1, because nginx is the client.
forwarded_allow_ips = "127.0.0.1"
access_log_format = '%({X-Forwarded-For}i)s %(t)s "%(r)s" %(s)s %(b)s %(M)sms'

proc_name = "crown"
