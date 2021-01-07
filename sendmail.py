#!/usr/bin/env python

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header


def to_utf8(s):
    if not isinstance(s, str):
        raise TypeError('`%s` must be of str type, got %s' % (s, type(s)))
    return s


class EmailClient(object):
    def __init__(self, server, port, username, password, ssl=True):
        self.server = server
        self.port = port
        self.username = username
        self.password = password
        self.ssl = ssl

    def sendmail(self, from_addr, to_addrs, subject, text, html=None):
        if isinstance(to_addrs, str):
            to_addrs = to_addrs.split(',')

        # Create message container - the correct MIME type is multipart/alternative.
        msg = MIMEMultipart('alternative')

        msg['From'] = from_addr
        msg['To'] = ','.join(to_addrs)
        msg['Subject'] = Header(to_utf8(subject), 'utf-8')

        # Record the MIME types of both parts - text/plain and text/html.
        part1 = MIMEText(text, 'plain')

        # Attach parts into message container.
        # According to RFC 2046, the last part of a multipart message, in this case
        # the HTML message, is best and preferred.
        msg.attach(part1)

        if html:
            part2 = MIMEText(html, 'html')
            msg.attach(part2)

        msg_str = msg.as_string()

        # pass self.server to fix for Python 3.7: https://stackoverflow.com/a/53385409/596206
        smtp = smtplib.SMTP(self.server)
        smtp.connect(self.server, self.port)
        smtp.ehlo()
        if self.ssl:
            smtp.starttls()
            smtp.ehlo()
        if self.username:
            smtp.login(self.username, self.password)
        smtp.sendmail(from_addr, to_addrs, msg_str)
        smtp.quit()


if __name__ == '__main__':
    import sys

    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    SMTP_SSL = os.environ.get('SMTP_SSL', True)

    client = EmailClient(SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_SSL)

    mail_args = sys.argv[1:]
    assert len(mail_args) in (4, 5)
    if len(mail_args) == 5:
        with open(mail_args[-1], 'r') as f:
            html = f.read()
        mail_args[-1] = html
    client.sendmail(*tuple(mail_args))
