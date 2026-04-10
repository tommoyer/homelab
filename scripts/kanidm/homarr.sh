#!/bin/bash

kanidm group create homarr_users
kanidm group create homarr_admins

kanidm system oauth2 create homarr Homarr https://homarr.moyer.wtf
kanidm system oauth2 add-redirect-url homarr https://homarr.moyer.wtf/api/auth/callback/oidc
kanidm system oauth2 update-scope-map homarr homarr_users openid groups email profile
kanidm system oauth2 prefer-short-username homarr

kanidm group add-members homarr_users tmoyer
kanidm group add-members homarr_admins tmoyer

kanidm system oauth2 show-basic-secret homarr
