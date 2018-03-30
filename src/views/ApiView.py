# -*- coding: utf-8 -*-
"""
    passport.views.ApiView
    ~~~~~~~~~~~~~~

    The blueprint for api view.

    :copyright: (c) 2017 by staugur.
    :license: MIT, see LICENSE for more details.
"""
import json
import base64
import os.path
from config import UPYUN as Upyun
from utils.send_email_msg import SendMail
from utils.upyunstorage import CloudStorage
from utils.web import email_tpl, dfr, apilogin_required, apiadminlogin_required, VaptchaApi
from utils.tool import logger, generate_verification_code, email_check, phone_check, ListEqualSplit,  gen_rnd_filename, allowed_file
from flask import Blueprint, request, jsonify, g
from werkzeug import secure_filename

# 初始化前台蓝图
ApiBlueprint = Blueprint("api", __name__)


@ApiBlueprint.route('/miscellaneous/_sendVcode', methods=['POST'])
def misc_sendVcode():
    """发送验证码：邮箱、手机"""
    res = dict(msg=None, success=False)
    account = request.form.get("account")
    if email_check(account):
        email = account
        key = "passport:signUp:vcode:{}".format(email)
        try:
            hasKey = g.redis.exists(key)
        except Exception, e:
            logger.error(e, exc_info=True)
            res.update(msg="System is abnormal")
        else:
            if hasKey:
                res.update(msg="Have sent the verification code, please check the mailbox")
            else:
                # 初始化邮箱发送服务
                sendmail = SendMail()
                vcode = generate_verification_code()
                result = sendmail.SendMessage(to_addr=email, subject=u"Passport邮箱注册验证码", formatType="html", message=email_tpl % (email, u"注册", vcode))
                if result["success"]:
                    try:
                        g.redis.set(key, vcode)
                        g.redis.expire(key, 300)
                    except Exception, e:
                        logger.error(e, exc_info=True)
                        res.update(msg="System is abnormal")
                    else:
                        res.update(msg="Sent verification code, valid for 300 seconds", success=True)
                else:
                    res.update(msg="Mail delivery failed, please try again later")
    elif phone_check(account):
        res.update(msg="Not support phone number registration")
    else:
        res.update(msg="Invalid account")
    logger.debug(res)
    return jsonify(dfr(res))


@ApiBlueprint.route("/miscellaneous/_getDownTime")
def misc_getDownTime():
    """Vaptcha宕机模式接口"""
    # 初始化手势验证码服务
    vaptcha = VaptchaApi()
    return jsonify(vaptcha.getDownTime)


@ApiBlueprint.route("/user/app/", methods=["GET", "POST", "PUT", "DELETE"])
@apiadminlogin_required
def userapp():
    """管理接口"""
    res = dict(msg=None, code=1)
    if request.method == "GET":
        # 定义参数
        sort = request.args.get("sort") or "desc"
        page = request.args.get("page") or 1
        limit = request.args.get("limit") or 10
        # 参数检查
        try:
            page = int(page)
            limit = int(limit)
            page -= 1
            if page < 0:
                raise
        except:
            res.update(code=2, msg="There are invalid parameters")
        else:
            # 从封装类中获取数据
            res.update(g.api.userapp.listUserApp())
            data = res.get("data")
            if data and isinstance(data, (list, tuple)):
                data = [i for i in sorted(data, reverse=False if sort == "asc" else True)]
                count = len(data)
                data = ListEqualSplit(data, limit)
                pageCount = len(data)
                if page < pageCount:
                    res.update(code=0, data=data[page], pageCount=pageCount, page=page, limit=limit, count=count)
                else:
                    res.update(code=3, msg="There are invalid parameters")
            else:
                res.update(code=4, msg="No data")
    elif request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        app_redirect_url = request.form.get("app_redirect_url")
        res.update(g.api.userapp.createUserApp(name=name, description=description, app_redirect_url=app_redirect_url))
    elif request.method == "PUT":
        name = request.form.get("name")
        description = request.form.get("description")
        app_redirect_url = request.form.get("app_redirect_url")
        res.update(g.api.userapp.updateUserApp(name=name, description=description, app_redirect_url=app_redirect_url))
    elif request.method == "DELETE":
        name = request.form.get("name")
        res.update(g.api.userapp.deleteUserApp(name=name))
    logger.info(res)
    return jsonify(dfr(res))


@ApiBlueprint.route("/user/profile/", methods=["GET", "POST", "PUT"])
@apilogin_required
def userprofile():
    res = dict(msg=None, code=1)
    if request.method == "GET":
        getBind = True if request.args.get("getBind") in ("true", "True", True) else False
        res = g.api.userprofile.getUserProfile(g.uid, getBind)
    elif request.method == "PUT":
        """修改个人资料，包含：基本资料、密码、头像、社交账号绑定"""
        Action = request.args.get("Action")
        if Action == "profile":
            data = {k: v for k, v in request.form.iteritems() if k in ("nick_name", "domain_name", "birthday", "location", "gender", "signature")}
            res = g.api.userprofile.updateUserProfile(uid=g.uid, **data)
            if res["code"] == 0:
                # 同步基本资料
                g.api.usersso.clientsConSync(g.api.userapp.getUserApp, g.uid, dict(CallbackType="user_profile", CallbackData=data))
        elif Action == "password":
            nowpass = request.form.get("nowpass")
            newpass = request.form.get("newpass")
            repass = request.form.get("repass")
            res = g.api.userprofile.updateUserPassword(uid=g.uid, nowpass=nowpass, newpass=newpass, repass=repass)
    logger.info(res)
    return jsonify(dfr(res))


@ApiBlueprint.route("/user/message/", methods=["GET", "POST", "DELETE"])
@apilogin_required
def usermsg():
    res = dict(msg=None, code=1)
    Action = request.args.get("Action")
    if request.method == "POST":
        if Action == "addMessage":
            res = g.api.usermsg.push_message(g.uid, request.form.get("msgContent"), request.form.get("msgType", "system"))
        elif Action == "markMessage":
            res = g.api.usermsg.markstatus_message(g.uid, request.form.get("msgId"))
    elif request.method == "GET":
        if Action == "getCount":
            res = g.api.usermsg.count_message(g.uid, request.args.get("msgStatus") or 1)
        elif Action == "getList":
            res = g.api.usermsg.pull_message(g.uid, request.args.get("msgStatus") or 1, request.args.get("msgType"), True if request.args.get("desc", True) in (True, "True", "true") else False)
    elif request.method == "DELETE":
        if Action == "delMessage":
            res = g.api.usermsg.delete_message(g.uid, request.form.get("msgId"))
        elif Action == "clearMessage":
            res = g.api.usermsg.clear_message(g.uid)
    logger.info(res)
    return jsonify(dfr(res))


'''
@ApiBlueprint.route('/user/upload/', methods=['POST', 'OPTIONS'])
@apilogin_required
def userupload():
    # 通过表单形式上传图片
    res = dict(code=1, msg=None)
    logger.debug(request.files)
    f = request.files.get('file')
    callableAction = request.args.get("callableAction")
    if f and allowed_file(f.filename):
        filename = secure_filename(gen_rnd_filename() + "." + f.filename.split('.')[-1])  # 随机命名
        basedir = Upyun['basedir'] if Upyun['basedir'].startswith('/') else "/" + Upyun['basedir']
        imgUrl = os.path.join(basedir, filename)
        try:
            upyunapi.put(imgUrl, f.stream.read())
        except Exception, e:
            logger.error(e, exc_info=True)
            res.update(code=2, msg="System is abnormal")
        else:
            imgUrl = Upyun['dn'].strip("/") + imgUrl
            res.update(imgUrl=imgUrl, code=0)
            if callableAction == "UpdateAvatar":
                resp = g.api.userprofile.updateUserAvatar(uid=g.uid, avatarUrl=imgUrl)
                res.update(resp)
                if resp["code"] == 0:
                    # 同步头像
                    g.api.usersso.clientsConSync(g.api.userapp.getUserApp, g.uid, dict(CallbackType="user_avatar", CallbackData=imgUrl))
    else:
        res.update(code=3, msg="Unsuccessfully obtained file or format is not allowed")
    logger.info(res)
    return jsonify(dfr(res))
'''

@ApiBlueprint.route('/user/upload/', methods=['POST', 'OPTIONS'])
@apilogin_required
def userupload():
    # 通过base64形式上传图片
    res = dict(code=1, msg=None)
    picStr = request.form.get('picStr')
    callableAction = request.args.get("callableAction")
    if picStr:
        basedir = Upyun['basedir'] if Upyun['basedir'].startswith('/') else "/" + Upyun['basedir']
        imgUrl = os.path.join(basedir, gen_rnd_filename() + ".png")
        try:
            # 又拍云存储封装接口
            upyunapi = CloudStorage(timeout=15)
            upyunapi.put(imgUrl, base64.b64decode(picStr))
        except Exception, e:
            logger.error(e, exc_info=True)
            res.update(code=2, msg="System is abnormal")
        else:
            imgUrl = Upyun['dn'].strip("/") + imgUrl
            res.update(imgUrl=imgUrl, code=0)
            if callableAction == "UpdateAvatar":
                resp = g.api.userprofile.updateUserAvatar(uid=g.uid, avatarUrl=imgUrl)
                res.update(resp)
                if resp["code"] == 0:
                    # 同步头像
                    g.api.usersso.clientsConSync(g.api.userapp.getUserApp, g.uid, dict(CallbackType="user_avatar", CallbackData=imgUrl))
    else:
        res.update(code=3, msg="Unsuccessfully obtained file or format is not allowed")
    logger.info(res)
    return jsonify(dfr(res))