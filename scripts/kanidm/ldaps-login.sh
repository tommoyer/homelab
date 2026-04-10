#!/bin/bash

kanidm group create linux_users
kanidm group create linux_admins

kanidm group add-members linux_users tmoyer
kanidm group add-members linux_admins tmoyer

kanidm group posix set --name tmoyer linux_users
kanidm group posix set --name tmoyer linux_admins

kanidm person posix set --name tmoyer tmoyer --shell /bin/bash
kanidm person posix set-password --name tmoyer tmoyer