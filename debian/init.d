#!/bin/sh -e

### BEGIN INIT INFO
# Provides:          sie-update
# Required-Start:    $remote_fs $syslog $network
# Required-Stop:     $remote_fs $syslog $network
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
### END INIT INFO

PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
DAEMON=/usr/sbin/sie-update
NAME=sie-update
DESC=sie-update
PIDFILE=/var/run/$NAME.pid

if [ -f /etc/default/$NAME ]; then
    . /etc/default/sie-update
fi

test -x $DAEMON || exit 0
test ! -z "$INTERFACE" || exit 0

. /lib/lsb/init-functions

case "$1" in
  start)
	log_begin_msg "Starting $DESC:" "$NAME"
	if start-stop-daemon --start --quiet --oknodo --pidfile $PIDFILE --name python --startas "$DAEMON" -- -i "$INTERFACE" -d; then
	    log_end_msg 0
	else
	    log_end_msg 1
	fi
	;;
  stop)
	log_begin_msg "Stopping $DESC:" "$NAME"
	if start-stop-daemon --stop --quiet --oknodo --pidfile $PIDFILE --name python; then
	   log_end_msg 0
	else
	   log_end_msg 1
	fi
	;;
  restart|reload|force-reload)
	$0 stop
	$0 start
	;;
  status)
	status_of_proc $DAEMON $NAME
	exit $?
	;;
  *)
	N=/etc/init.d/$NAME
	echo "Usage: $N {start|stop|restart|reload|force-reload|status}" >&2
	exit 1
	;;
esac

exit 0
