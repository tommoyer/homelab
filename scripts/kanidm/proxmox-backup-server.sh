#!/bin/bash

kanidm group create pbs_users

kanidm system oauth2 create pbs PBS https://pbs.ts.moyer.wtf
kanidm system oauth2 add-redirect-url pbs https://pbs.ts.moyer.wtf
kanidm system oauth2 update-scope-map pbs pbs_users openid email profile groups

kanidm group add-members pbs_users tmoyer

kanidm system oauth2 show-basic-secret pbs
