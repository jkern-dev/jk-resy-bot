# resy-bot
## Introduction
This is a reservation booking bot designed to snipe reservations from [Resy](https://resy.com/) using the 
[Resy API](http://subzerocbd.info/) for the upcoming weekends (will look at next 8 weeks by default).
The bot will wake up and run every 5 seconds and on each run, will search all restaurants in your Resy Hit List
for available reservations on any of the next four weekends. Using a config file, you can set preferences like
the ideal reservation time as well as the acceptable timeperiod before or after that time for grabbing a table,
which restaurants to prioritize for a given weekend, how long a gap to mandate between your last visit to a restaurant
before rebooking, etc.
To allow for dynamic updating of the config, the bot will pull the config file from Dropbox, for which you'll need to create
a token separately. If you want to use a local file only, you can do so through a flag on invocation.

## Usage
The best way to run the bot is through Docker.
To get started, you must create a `startup_config.yaml` file within the `config_files` directory.
Look at the sample configs provided to get a sense of what you need to define.

```
./run-bot.sh [--detach]
```

## Config File
The config files provided must be in YAML format.
To get started make a copy of sample_startup_config.yaml in the `config_files` directory.
If you want to just run with a local resy config file, you can create a copy of the `sample_resy_config.yaml`
and name it `resy_config.yaml` and set your correct credentials and timezone. Then, in your `startup_config.yaml`,
set `local_config_only` to True.

Remember to have a credit card on file in your account. Some reservations require a credit card before making 
a reservation in case of late cancellations or no-shows. Not having one will result in the snipe to fail!

## Features

* Will only grab a table at a restaurant if it's within an acceptable time period
* Will ignore any restaurant where you've been in the recent past (defaults to the last 90 days)
* Will ignore any restaurants where you have an upcoming reservation (including reservations made by the bot in realtime)
* Will only book non refundable reservations if specified (defaults to no)
* Will only book prepaid reservations if you'll have more than 24 hours to cancel without penalty from when it books the table

# How to find your Resy API Key

In order for the bot to act like you on Resy, along with logging in, it also needs to provide an API key that is unique to your account.
Unfortunately, the only way to get this key is by logging into Resy through your browser and then inspecting network traffic.
Once you're logged in, right click on the page -> Inspect -> Network
Now search for any restaurant and look for a call made to `api.resy.com` for `search`.
Look at the Authorization request header for this call. The value will be something like `ResyAPI api_key="your_api_key"`.
Grab the value inside the quotes and put it in your config.yaml file.