#!/bin/bash

kanidm group create mealie_users
kanidm group create mealie_admins

kanidm system oauth2 create mealie "Mealie" https://mealie.moyer.wtf
kanidm system oauth2 add-redirect-url mealie https://mealie.moyer.wtf/login
kanidm system oauth2 prefer-short-username mealie
kanidm system oauth2 update-scope-map mealie mealie_users openid email profile groups
kanidm system oauth2 update-scope-map mealie mealie_admins openid email profile groups

kanidm group add-members mealie_users tmoyer
kanidm group add-members mealie_admins tmoyer

kanidm system oauth2 show-basic-secret mealie
