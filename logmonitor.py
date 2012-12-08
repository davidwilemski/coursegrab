from tinyfeedback.helper import tail_monitor

class LastVal(object):
    def __init__(self, val=0):
        self.send(val)
    def next(self):
        return self.val
    def send(self, val):
        self.val = val

value = LastVal()

def parse_line(data, line):
    if 'GET / HTTP/1.1' in line:
        data['site.hits'] += 1

    if 'closed classes' in line and 'no need' not in line:
        count = line.split()[-3]
        value.send(count)
    
    elif 'POST /twilio_receive' in line:
        data['sms.received'] += 1 
        data['sms.sent'] += 1 
    
    elif 'sending notification sms' in line:
        data['sms.sent'] += 1 

    data['classes.closed'] = value.next()

if __name__ == '__main__':
    global last_count
    tail_monitor(component='coursegrab',
            log_filename='/tmp/coursemaster.log',
            line_callback_func=parse_line,
            data_arg={'site.hits': 0, 'sms.received': 0, 'sms.sent': 0},
            )
