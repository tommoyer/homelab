#!/bin/bash

kanidm group create vaultwarden_users

kanidm system oauth2 create vaultwarden Vaultwarden https://vaultwarden.ts.moyer.wtf
kanidm system oauth2 add-redirect-url vaultwarden https://vaultwarden.ts.moyer.wtf
kanidm system oauth2 update-scope-map vaultwarden vaultwarden_users openid email profile 

kanidm group add-members vaultwarden_users tmoyer

kanidm system oauth2 show-basic-secret vaultwarden
