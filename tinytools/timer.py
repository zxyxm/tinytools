"""Countdown state independent of UI refresh speed."""
import math
import time


class Countdown:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = 'idle'
        self.duration = 300
        self._remaining = 300.0
        self.deadline = None

    @property
    def remaining(self):
        if self.state == 'running':
            return max(0.0, self.deadline - self.clock())
        return self._remaining

    @property
    def display(self):
        seconds = math.ceil(self.remaining)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}'

    def configure(self, seconds):
        if seconds <= 0:
            raise ValueError('倒计时必须大于零')
        if self.state in ('running', 'paused'):
            raise ValueError('请先重置，再修改时长')
        self.duration = int(seconds)
        self.reset()

    def start(self):
        if self.state == 'running':
            return
        if self.state == 'finished':
            self._remaining = float(self.duration)
        self.deadline = self.clock() + self._remaining
        self.state = 'running'

    def pause(self):
        if self.state == 'running':
            self._remaining = self.remaining
            self.state = 'paused'

    def reset(self):
        self.state = 'idle'
        self.deadline = None
        self._remaining = float(self.duration)

    def tick(self):
        if self.state == 'running' and self.remaining <= 0:
            self.state = 'finished'
            self._remaining = 0
            return True
        return False
