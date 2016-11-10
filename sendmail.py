#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# Could be `smtp-mail.outlook.com` or `smtp-mail.outlook.com:25`
SMTP_SERVER = os.environ['SMTP_SERVER']
SMTP_USERNAME = os.environ.get('SMTP_USERNAME')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
SMTP_SSL = os.environ.get('SMTP_SSL', False)


def sendmail(from_addr, to_addrs, subject, text, html=None):
    if isinstance(to_addrs, basestring):
        to_addrs = to_addrs.split(',')

    # Create message container - the correct MIME type is multipart/alternative.
    msg = MIMEMultipart('alternative')

    msg['From'] = from_addr
    msg['To'] = ','.join(to_addrs)
    msg['Subject'] = subject

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

    if SMTP_SSL:
        smtp = smtplib.SMTP_SSL()
    else:
        smtp = smtplib.SMTP()
    smtp.connect(SMTP_SERVER)
    if SMTP_USERNAME:
        try:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        except smtplib.SMTPException:
            print 'Try with SSL'
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
    smtp.sendmail(from_addr, to_addrs, msg_str)
    smtp.quit()


if __name__ == '__main__':
    import sys
    html = sys.stdin.read()
    html_args = []
    if html:
        html_args = [html]
    sendmail(*tuple(sys.argv[1:] + html_args))
