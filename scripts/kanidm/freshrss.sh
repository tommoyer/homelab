#!/bin/bash

kanidm group create freshrss_users
kanidm group create freshrss_admins

kanidm system oauth2 create freshrss FreshRSS https://freshrss.priv.moyer.wtf
kanidm system oauth2 add-redirect-url freshrss https://freshrss.priv.moyer.wtf/i/oidc
kanidm system oauth2 update-scope-map freshrss freshrss_users openid email profile groups
kanidm system oauth2 update-scope-map freshrss freshrss_admins openid email profile groups
kanidm system oauth2 warning-insecure-client-disable-pkce freshrss

kanidm group add-members freshrss_users tmoyer
kanidm group add-members freshrss_admins tmoyer

kanidm system oauth2 show-basic-secret freshrss
