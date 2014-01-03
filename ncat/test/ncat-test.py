#!/usr/bin/python -3

import subprocess
import threading
import sys
import traceback
import os
import time

if sys.version > '3':
    import queue
else:
    import Queue as queue

if sys.platform == "cygwin" or sys.platform.startswith("win"):
    import ctypes
    import msvcrt
    def make_nonblocking(fp):
        pass
    def do_read(fp):
        fh = msvcrt.get_osfhandle(fp.fileno())
        
else:
    import fcntl
    def make_nonblocking(fp):
        fd = fp.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    def do_read(fp):
        time.sleep(0.1)
        return fp.read()


NUM_THREADS = 2
WAIT_TIMEOUT = 0.1
tests = []


def ncat_test(name, xfail=False):
    def wrap(f):
        global tests
        f.name = name
        f.xfail = xfail
        tests += [f]
        return f
    return wrap


def ncat(arg):
    # TODO: replace "ncat" with an OS-dependent path to ncat.
    proc = subprocess.Popen(["ncat", arg],
                            stdout=subprocess.PIPE,
                            stdin=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    make_nonblocking(proc.stdout)
    make_nonblocking(proc.stderr)
    return proc


def do_write(fp, buf):
    fp.write(buf)
    fp.flush()



def assert_equal(arg1, arg2):
    assert arg1 == arg2, "Got %s, expected %s" % (repr(arg1), repr(arg2))

"""============================================================================

INDIVIDUAL TESTS START HERE

============================================================================"""


@ncat_test("Server default listen address and port IPv4")
def server_default_listen_address_and_port_ipv4():
    try:
        s = ncat("-lk")

        c = ncat("127.0.0.1")
        do_write(c.stdin, b"abc\n")
        assert_equal(do_read(s.stdout), b"abc\n")

        c2 = ncat("127.0.0.1")
        do_write(c2.stdin, b"abc\n")
        assert_equal(do_read(s.stdout), b"abc\n")

        return True
    finally:
            s.terminate()
            c.terminate()
            c2.terminate()
        except:
            pass

"""============================================================================

INDIVIDUAL TESTS END HERE

============================================================================"""


def tests_worker(q, unexpected_successes, successes, expected_failures,
                 failures):
    should_complete = False
    try:
        while True:
            test = q.get(timeout=WAIT_TIMEOUT)
            should_complete = True
            if test():
                msg = "PASS:\t%s" % test.name
                if test.xfail:
                    msg = "UNEX" + msg
                    unexpected_successes.put(test)
                else:
                    successes.put(test)
            else:
                msg = "FAIL:\t%s" % test.name
                if test.xfail:
                    msg = "X" + msg
                    expected_failures.put(test)
                else:
                    failures.put(test)
            print(msg)
            q.task_done()
            should_complete = False
    except queue.Empty:
        return
    except Exception as e:
        traceback.print_exc()
    finally:
        if should_complete:
            q.task_done()


def run_tests():
    successes = queue.Queue()
    failures = queue.Queue()
    unexpected_successes = queue.Queue()
    expected_failures = queue.Queue()
    q = queue.Queue()

    args = [q, unexpected_successes, successes, expected_failures, failures]
    for i in range(NUM_THREADS):
        t = threading.Thread(target=tests_worker, args=args)
        #t.daemon = True
        t.start()

    for test in tests:
        q.put(test)

    q.join()

    total_tests = sum((successes.qsize(), failures.qsize(),
                       unexpected_successes.qsize(),
                       expected_failures.qsize()))

    total_successes = successes.qsize() + expected_failures.qsize()
    if total_successes > 0:
        success_rate = total_successes / float(total_tests) * 100.0
    else:
        success_rate = 0.0

    print(("%d tests ran, %0.2f%% success rate (%d SUCC, %d FAIL, " +
           "%d UNEXSUCC, %d XFAIL)") % (total_tests, success_rate,
                                        successes.qsize(), failures.qsize(),
                                        unexpected_successes.qsize(),
                                        expected_failures.qsize()))

if __name__ == "__main__":
    run_tests()
