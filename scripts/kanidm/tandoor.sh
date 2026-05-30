#!/bin/bash

kanidm group create tandoor_users
kanidm group create tandoor_admins

kanidm system oauth2 create tandoor Tandoor https://tandoor.moyer.wtf
kanidm system oauth2 add-redirect-url tandoor https://tandoor.moyer.wtf/accounts/oidc/kanidm/login/callback/

kanidm system oauth2 update-scope-map tandoor tandoor_users openid email profile groups
kanidm system oauth2 update-scope-map tandoor tandoor_admins openid email profile groups
kanidm system oauth2 warning-insecure-client-disable-pkce tandoor

kanidm group add-members tandoor_users tmoyer
kanidm group add-members tandoor_users stacey
kanidm group add-members tandoor_users tori
kanidm group add-members tandoor_admins tmoyer

kanidm system oauth2 show-basic-secret tandoor
