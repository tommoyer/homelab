#!/bin/bash

kanidm group create netbox_users

kanidm system oauth2 create netbox "Netbox" https://netbox.priv.moyer.wtf
kanidm system oauth2 add-redirect-url netbox https://netbox.priv.moyer.wtf/complete/oidc/
kanidm system oauth2 add-redirect-url netbox https://netbox.moyer.wtf/oauth/complete/oidc/
kanidm system oauth2 update-scope-map netbox netbox_users openid email profile groups
kanidm system oauth2 warning-insecure-client-disable-pkce netbox
kanidm system oauth2 prefer-short-username netbox

kanidm group add-members netbox_users tmoyer

kanidm system oauth2 show-basic-secret netbox
