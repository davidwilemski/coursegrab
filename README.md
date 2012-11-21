#coursegrab

A tool for sending notifications when University of Michigan classes open up.

##Configuration

###Application settings
Coursegrab requires the following environment variables to be set:

- `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`: The Account SID and AUTH token found on your Twilio developer dashboard
- `TWILIO_SOURCE_NUMBER`: The twilio phone number to send sms from. Must be a phone number you own.

###Twilio Setup
The Twilio phone number used for `TWILIO_SOURCE_NUMBER` needs a SMS Request URL of 
`http://HOST:10001/twilio_receive` where `HOST` is the IP address or domain of the host you run
coursegrab from. The SMS Request URL should also be set to use `POST`.

###Datastore
Coursegrab uses Redis as a datastore and expects to find a
Redis server at `localhost:6379` (the default port).

##Running
First, make sure you have the dependancies installed using `pip`:

`pip install -r requirements.txt`

Then just execute `coursemaster.py`:

`python coursemaster.py`

##TODO

- Make Redis location configurable
- Manage the server process with supervisord
