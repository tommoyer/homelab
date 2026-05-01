#!/bin/bash

kanidm group create gitea_users
kanidm group create gitea_admins

kanidm system oauth2 create gitea Gitea https://gitea.priv.moyer.wtf/user/login
kanidm system oauth2 add-redirect-url gitea https://gitea.priv.moyer.wtf/user/oauth2/kanidm/callback
kanidm system oauth2 update-scope-map gitea gitea_users email openid profile groups
kanidm system oauth2 update-scope-map gitea gitea_admins openid groups email profile

kanidm group add-members gitea_users tmoyer
kanidm group add-members gitea_admins tmoyer

kanidm system oauth2 warning-insecure-client-disable-pkce gitea

kanidm system oauth2 show-basic-secret gitea
