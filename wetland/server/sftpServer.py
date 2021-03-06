import os
import re
import time
from wetland import config

from paramiko import ServerInterface, SFTPServerInterface, SFTPServer, \
                     SFTPAttributes, SFTPHandle, SFTP_OK, AUTH_SUCCESSFUL,\
                     OPEN_SUCCEEDED, SFTP_OP_UNSUPPORTED


class remote_sftp_handle(SFTPHandle):
    def __init__(self, file_name, output, remote_file, save_file):
        self.remote_file = remote_file
        self.file_name = file_name
        self.save_file = save_file
        self.opt = output

    def close(self):
        self.opt.o("sftpfile", 'close', self.filename)
        self.remote_file.close()
        if self.save_file:
            self.save_file.close()

    def read(self, offset, length):
        self.opt.o("sftpfile", 'read', self.filename)
        if not self.remote_file.readable():
            return SFTP_OP_UNSUPPORTED

        try:
            self.remote_file.seek(offset)
            data = self.remote_file.read(length)
            return data
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)

    def write(self, offset, data):
        self.opt.o("sftpfile", 'write', self.filename)
        if not self.remote_file.writable():
            return SFTP_OP_UNSUPPORTED

        try:
            self.remote_file.seek(offset)
            self.remote_file.write(data)
            self.remote_file.flush()

            self.save_file.seek(offset)
            self.save_file.write(data)
            self.save_file.flush()
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def stat(self):
        self.opt.o("sftpfile", 'stat', self.filename)
        try:
            return self.remote_file.stat()
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        else:
            return SFTP_OK

    def chattr(self, attr):
        self.opt.o("sftpfile", 'chattr', self.filename)
        try:
            self.remote_file.chattr(attr)

        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        else:
            return SFTP_OK


class sftp_server (SFTPServerInterface):
    def __init__(self, ssh_server):
        self.ssh_server = ssh_server
        self.docker_client = ssh_server.docker_trans.open_sftp_client()
        self.root = self.docker_client.getcwd()

        self.cfg = config.cfg
        self.opt = ssh_server.opt
        self.opt.o("sftpserver", 'init', 'success')

    def canonicalize(self, path):
        return self.docker_client.normalize(path)

    def list_folder(self, path):
        self.opt.o("sftpserver", 'list', path)
        try:
            return self.docker_client.listdir_attr(path)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        self.opt.o("sftpserver", 'stat', path)
        try:
            return self.docker_client.stat(path)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)

    def lstat(self, path):
        self.opt.o("sftpserver", 'lstat', path)
        try:
            return self.docker_client.lstat(path)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)

    def open(self, path, flags, attr):

        binary_flag = getattr(os, 'O_BINARY',  0)
        flags |= binary_flag
        save_file = None

        if (flags & os.O_CREAT) and (attr is not None):
            attr._flags &= ~attr.FLAG_PERMISSIONS
            self.chattr(path, attr)

        if flags & os.O_WRONLY:
            if flags & os.O_APPEND:
                fstr = 'ab'
            else:
                fstr = 'wb'
            save_dir = self.cfg.get("files", "sftp")
            file_name = [self.ssh_server.hacker_ip]
            file_name.append(time.strftime('%Y%m%d%H%M%S'))
            file_name.append(re.sub('[^A-Za-z0-0]', '-', path))
            file_name = '_'.join(file_name)
            save_path = os.path.join(save_dir, file_name)
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
            save_file = open(save_path, fstr)

        elif flags & os.O_RDWR:
            if flags & os.O_APPEND:
                fstr = 'a+b'
            else:
                fstr = 'r+b'
        else:
            # O_RDONLY (== 0)
            fstr = 'rb'

        self.opt.o("sftpserver", 'open', path)
        try:
            remote_file = self.docker_client.file(path, fstr)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)

        fobj = remote_sftp_handle(path, self.opt, remote_file, save_file)
        return fobj

    def remove(self, path):
        self.opt.o("sftpserver", 'remove', path)
        try:
            self.docker_client.remove(path)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        else:
            return SFTP_OK

    def rename(self, oldpath, newpath):
        self.opt.o("sftpserver", 'rename', '->'.join((oldpath, newpath)))
        try:
            self.docker_client.rename(oldpath, newpath)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        else:
            return SFTP_OK

    def mkdir(self, path, attr):
        self.opt.o("sftpserver", 'mkdir', path)
        try:
            self.docker_client.mkdir(path)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        else:
            return SFTP_OK

    def rmdir(self, path):
        self.opt.o("sftpserver", 'rmdir', path)
        try:
            self.docker_client.rmdir(path)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def chattr(self, path, attr):
        self.opt.o("sftpserver", 'chattr', path)
        try:
            if attr._flags & attr.FLAG_PERMISSIONS:
                self.docker_client.chmod(path, attr.st_mode)
                self.logger.info("chmod mod:%o path:%s" % (attr.st_mode, path))

            if attr._flags & attr.FLAG_UIDGID:
                self.docker_client.chown(path, attr.st_uid, attr.st_gid)
                self.logger.info("chown uid:%d gid:%d path:%s" % (
                                              attr.st_uid, attr.st_gid, path))

            if attr._flags & attr.FLAG_AMTIME:
                self.docker_client.utime(path,
                                         (attr.st_atime, attr.st_mtime))
                self.logger.info("utime atime:%d stime:%d path:%s" % (
                                          attr.st_atime, attr.st_mtime, path))

            if attr._flags & attr.FLAG_SIZE:
                self.docker_client.truncate(path, attr.st_size)
                self.logger.info("truncate size:%d path:%s" % (attr.st_size,
                                                               path))

        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        else:
            return SFTP_OK

    def symlink(self, target_path, path):
        self.opt.o("sftpserver", 'symlink', '->'.join(target_path, path))
        try:
            self.docker_client.symlink(target_path, path)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def readlink(self, path):
        self.opt.o("sftpserver", 'readlink', path)
        try:
            symlink = self.docker_client.readlink(path)
        except IOError as e:
            return SFTPServer.convert_errno(e.errno)
        return symlink
