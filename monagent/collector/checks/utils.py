import base64
import binascii
import os
import stat

# os.SEEK_END is defined in python 2.5
SEEK_END = 2


def median(vals):
    vals = sorted(vals)
    if not vals:
        raise ValueError(vals)
    elif len(vals) % 2 == 0:
        i1 = int(len(vals) / 2)
        i2 = i1 - 1
        return float(vals[i1] + vals[i2]) / 2.
    else:
        return vals[int(len(vals) / 2)]


def add_basic_auth(request, username, password):
    """A helper to add basic authentication to a urllib2 request.

    We do this across a variety of checks so it's good to have this in one place.
    """
    auth_str = base64.encodestring('%s:%s' % (username, password)).strip()
    request.add_header('Authorization', 'Basic %s' % auth_str)
    return request


class TailFile(object):

    CRC_SIZE = 16

    def __init__(self, logger, path, callback):
        self._path = path
        self._f = None
        self._inode = None
        self._size = 0
        self._crc = None
        self._log = logger
        self._callback = callback

    def _open_file(self, move_end=False, pos=False):

        already_open = False
        # close and reopen to handle logrotate
        if self._f is not None:
            self._f.close()
            self._f = None
            already_open = True

        stat = os.stat(self._path)
        inode = stat[stat.ST_INO]
        size = stat[stat.ST_SIZE]

        # Compute CRC of the beginning of the file
        crc = None
        if size >= self.CRC_SIZE:
            tmp_file = open(self._path, 'r')
            data = tmp_file.read(self.CRC_SIZE)
            crc = binascii.crc32(data)

        if already_open:
            # Check if file has been removed
            if self._inode is not None and inode != self._inode:
                self._log.debug("File removed, reopening")
                move_end = False
                pos = False

            # Check if file has been truncated
            elif self._size > 0 and size < self._size:
                self._log.debug("File truncated, reopening")
                move_end = False
                pos = False

            # Check if file has been truncated and too much data has
            # alrady been written (copytruncate and opened files...)
            if size >= self.CRC_SIZE and self._crc is not None and crc != self._crc:
                self._log.debug("Begining of file modified, reopening")
                move_end = False
                pos = False

        self._inode = inode
        self._size = size
        self._crc = crc

        self._f = open(self._path, 'r')
        if move_end:
            self._log.debug("Opening file %s" % (self._path))
            self._f.seek(0, SEEK_END)
        elif pos:
            self._log.debug("Reopening file %s at %s" % (self._path, pos))
            self._f.seek(pos)

        return True

    def tail(self, line_by_line=True, move_end=True):
        """Read line-by-line and run callback on each line.

        line_by_line: yield each time a callback has returned True
        move_end: start from the last line of the log
        """
        try:
            self._open_file(move_end=move_end)

            while True:
                pos = self._f.tell()
                line = self._f.readline()
                if line:
                    line = line.strip(chr(0))  # a truncate may have create holes in the file
                    if self._callback(line.rstrip("\n")):
                        if line_by_line:
                            yield True
                            pos = self._f.tell()
                            self._open_file(move_end=False, pos=pos)
                        else:
                            continue
                    else:
                        continue
                else:
                    yield True
                    assert pos == self._f.tell()
                    self._open_file(move_end=False, pos=pos)

        except Exception as e:
            # log but survive
            self._log.exception(e)
            raise StopIteration(e)
