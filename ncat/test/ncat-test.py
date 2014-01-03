#!/usr/bin/python -3

"""
ncat-test.py

Runs Ncat unit tests in parallel.
"""

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
        """
        Switch the given object to non-blocking mode.

        Does nothing under Windows.
        """
        pass
    def do_read(fp):
        """
        Read all the data from the given subprocess PIPE without blocking the
        main loop.
        """
        fh = msvcrt.get_osfhandle(fp.fileno())
        # TODO: call PeekNamedPipe on the HANDLE to find out how many bytes
        # are waiting and read them.
else:
    import fcntl
    def make_nonblocking(fp):
        """
        Switch the given object to non-blocking mode.
        """
        fd = fp.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    def do_read(fp):
        """
        Read all the data from the given subprocess PIPE without blocking the
        main loop.
        """
        time.sleep(0.1)  # FIXME: perhaps there's a better way?
        return fp.read()


NUM_THREADS = 2
WAIT_TIMEOUT = 0.1
TESTS = []
STDOUT_LOCK = threading.Lock()


def ncat_test(name, xfail=False):
    """
    Decorator for the Ncat tests. Stores a reference to the function in the
    "tests" global variable and adds metadata to its object.
    """
    def wrap(f):
        global TESTS
        f.name = name
        f.xfail = xfail
        TESTS += [f]
        return f
    return wrap


def ncat(*args):
    """
    Spawns an Ncat process with the given arguments and returns its object.
    """
    # TODO: replace "ncat" with an OS-dependent path to ncat.
    proc = subprocess.Popen(["ncat"] + list(args),
                            stdout=subprocess.PIPE,
                            stdin=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    make_nonblocking(proc.stdout)
    make_nonblocking(proc.stderr)
    return proc


def do_write(fp, buf):
    """
    Convenience function that writes to the process's given pipe and
    flushes it.
    """
    fp.write(buf)
    fp.flush()



def assert_equal(arg1, arg2):
    """
    Convenience function that asserts that arg1 == arg2 and throws an
    AssertionError with a meaningful message if this does not happen.
    """
    assert arg1 == arg2, "Got %s, expected %s" % (repr(arg1), repr(arg2))

# =============================================================================
#
# INDIVIDUAL TESTS START HERE
#
# =============================================================================


@ncat_test("Server default listen address and port IPv4")
def server_default_listen_address_and_port_ipv4():
    """
    Run Ncat server, then connect to it over IPv4 and IPv6 using Ncat.
    """
    try:
        s = ncat("-lk")

        c = ncat("127.0.0.1")
        do_write(c.stdin, b"abc\n")
        assert_equal(do_read(s.stdout), b"abc\n")

        c2 = ncat("-6", "::1")
        do_write(c2.stdin, b"abc\n")
        assert_equal(do_read(s.stdout), b"abc\n")

        return True
    finally:
        s.terminate()
        c.terminate()
        c2.terminate()

# =============================================================================
#
# INDIVIDUAL TESTS END HERE
#
# =============================================================================


def tests_worker(q, unexpected_successes, successes, expected_failures,
                 failures):
    """
    Code for the Ncat testing worker. Reads the tasks from the queue, runs
    them, interprets the results and prints runtime information.
    """
    should_complete = False  # should we perform q.task_done in case of an
                             # ugly exception?
    try:
        while True:
            test = q.get(timeout=WAIT_TIMEOUT)
            should_complete = True

            success = False
            error_msg = ""
            try:
                success = test()
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lineno = traceback.extract_tb(exc_traceback)[1][1]
                error_msg = " (line %d: %s)" % (lineno, repr(e))

            if success:
                msg = "SUCC:\t%s" % test.name
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

            STDOUT_LOCK.acquire()
            print(msg + error_msg)
            STDOUT_LOCK.release()

            q.task_done()
            should_complete = False
    except queue.Empty:
        return
    finally:
        if should_complete:
            q.task_done()


def run_tests():
    """
    Set up the queues, run the workers and distribute the tasks. Once done,
    print the summary.
    """

    # The following queues are basically there in order to count how many
    # tests belong to the individual groups in a thread-safe way.
    successes = queue.Queue()
    failures = queue.Queue()
    unexpected_successes = queue.Queue()
    expected_failures = queue.Queue()

    q = queue.Queue()

    args = [q, unexpected_successes, successes, expected_failures, failures]
    for _ in range(NUM_THREADS):
        t = threading.Thread(target=tests_worker, args=args)
        #t.daemon = True # TODO: which is better here?
        t.start()

    for test in TESTS:
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
