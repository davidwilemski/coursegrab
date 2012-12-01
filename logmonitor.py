from tinyfeedback.helper import tail_monitor

def parse_line(data, line):
    if 'GET / HTTP/1.1' in line:
        data['site.hits'] += 1

    elif 'closed classes' in line and 'no need' not in line:
        count = line.split()[-3]
        data['classes.closed'] = count
    
    elif 'POST /twilio_receive' in line:
        data['sms.received'] += 1 

if __name__ == '__main__':
    global last_count
    tail_monitor(component='coursegrab',
            log_filename='/tmp/coursemaster.log',
            line_callback_func=parse_line,
            data_arg={'site.hits': 0, 'sms.received':0},
            )
