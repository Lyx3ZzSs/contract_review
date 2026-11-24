"""Tianyancha transport and display fields, verified against official API metadata."""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

# Official protocol source: https://open.tianyancha.com/open-admin/interface/uni.json?id={id}
ENDPOINTS = {
    'basic': ('企业基本信息', '1116', '/services/open/ic/baseinfo/normal'),
    'shareholders': ('股东信息', '821', '/services/open/ic/holder/2.0'),
    'ownership': ('企业属性', '1154', '/services/open/ic/companyType/3.0'),
    'scale': ('企业规模', '1149', '/services/open/ic/scale'),
    'dishonesty': ('失信信息', '843', '/services/open/jr/dishonest/2.0'),
    'execution': ('被执行人', '839', '/services/open/jr/zhixinginfo/2.0'),
    'illegal': ('严重违法', '846', '/services/open/mr/illegalinfo/2.0'),
    'abnormal': ('经营异常', '848', '/services/open/mr/abnormal/2.0'),
    'tax': ('税务非正常户', '1178', '/services/open/mr/improperTaxpayer'),
    'bankruptcy': ('破产重整', '1036', '/services/open/jr/bankruptcy/2.0'),
    'bankruptcy_detail': ('破产重整详情', '1037', '/services/open/jr/bankruptcy/detail/2.0'),
}
RISKS = {key: ENDPOINTS[key][:2] for key in ('dishonesty', 'execution', 'illegal', 'abnormal', 'tax', 'bankruptcy')}
MODULES = (*RISKS, 'ownership', 'scale', 'shareholders')
PAGED = {*RISKS, 'shareholders'}
PAGE_SIZE = 20
ERRORS = {
    300000: ('empty', '本次查询未发现相关记录'),
    300002: ('unavailable', '天眼查账号失效'),
    300003: ('unavailable', '天眼查账号过期'),
    300004: ('failed', '访问频率过快，请稍后重试'),
    300005: ('unavailable', '当前天眼查账号未开通此项，开通后可重新查询'),
    300006: ('unavailable', '天眼查接口余额不足，充值后可重新查询'),
    300007: ('unavailable', '天眼查接口剩余次数不足'),
    300008: ('failed', '数据服务参数校验失败'),
    300009: ('unavailable', '天眼查账号信息有误'),
    300010: ('failed', '数据服务接口地址不存在'),
    300011: ('unavailable', '当前服务器 IP 未获天眼查授权'),
}
FIELDS = {
    'dishonesty': [('iname', '失信人名称'), ('casecode', '案号'), ('courtname', '执行法院'), ('regdate', '立案日期'), ('publishdate', '发布日期'), ('amountInvolved', '涉案金额（元）'), ('performance', '履行情况'), ('disrupttypename', '失信行为'), ('duty', '生效法律文书确定的义务'), ('performedPart', '已履行部分'), ('unperformPart', '未履行部分'), ('gistid', '执行依据文号'), ('gistunit', '执行依据单位')],
    'execution': [('pname', '被执行人'), ('caseCode', '案号'), ('execCourtName', '执行法院'), ('caseCreateTime', '立案日期'), ('execMoney', '执行标的（元）')],
    'illegal': [('putReason', '列入原因'), ('putDate', '列入日期'), ('putDepartment', '列入机关'), ('removeDate', '移除日期'), ('removeReason', '移除原因'), ('removeDepartment', '移除机关')],
    'abnormal': [('putReason', '列入原因'), ('putDate', '列入日期'), ('putDepartment', '列入机关'), ('removeDate', '移出日期'), ('removeReason', '移出原因'), ('removeDepartment', '移出机关')],
    'tax': [('taxpayerName', '纳税人名称'), ('taxpayerNumber', '纳税人识别号'), ('certifyDate', '认定日期'), ('certifyOrg', '认定机关'), ('certifyReason', '认定原因'), ('businessAddress', '经营地点')],
    'bankruptcy': [('caseNo', '案号'), ('caseType', '案件类型'), ('status', '案件状态'), ('submitTime', '公开日期'), ('respondent', '被申请人'), ('applicant', '申请人')],
    'bankruptcy_detail': [('caseNo', '案号'), ('caseType', '案件类型'), ('submitTime', '公开日期'), ('respondent', '被申请人'), ('applicant', '申请人'), ('court', '法院'), ('managerialAgency', '管理人机构'), ('managerPrincipal', '管理人负责人')],
}
DATE_FIELDS = {'regdate', 'publishdate', 'caseCreateTime', 'putDate', 'removeDate', 'certifyDate', 'submitTime'}


def settings():
    values = {}
    path = Path(__file__).resolve().parents[1] / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip()
    url = os.getenv('TIANYANCHA_API_URL', values.get('TIANYANCHA_API_URL', 'https://open.api.tianyancha.com')).rstrip('/')
    if url == 'http://open.api.tianyancha.com':
        url = 'https://open.api.tianyancha.com'
    return url, os.getenv('TIANYANCHA_TOKEN', values.get('TIANYANCHA_TOKEN', ''))


def display_value(key, value):
    if value is None or value == '' or value == []:
        return '未提供'
    if key in DATE_FIELDS and (isinstance(value, (int, float)) or str(value).isdigit()):
        try:
            return datetime.fromtimestamp(float(value) / 1000, ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        except (ValueError, OverflowError, OSError):
            return '日期格式待核对'
    if key == 'applicant' and isinstance(value, list):
        return '、'.join(str(x.get('applicantName') or '未提供') for x in value if isinstance(x, dict)) or '未提供'
    if key == 'status':
        return {0: '历史案件', 1: '当前案件'}.get(value, '状态未提供')
    return str(value)


def record(module, item):
    title = next((item[k] for k in ('casecode', 'caseCode', 'caseNo', 'putReason', 'taxpayerName') if item.get(k)), ENDPOINTS[module][0])
    result = {'title': str(title), 'fields': [{'label': label, 'value': display_value(key, item.get(key))} for key, label in FIELDS[module]]}
    if module == 'bankruptcy' and item.get('uuid'):
        result['detail_id'] = str(item['uuid'])
    return result


def query(module, keyword, page=1, *, detail_id=None):
    url, token = settings()
    if not token:
        return {'state': 'unavailable', 'message': '未配置天眼查凭证', 'data': None}
    if module not in ENDPOINTS:
        return {'state': 'unavailable', 'message': '不支持的查询项目', 'data': None}
    params = {'keyword': keyword}
    if module in PAGED:
        params.update(pageNum=page, pageSize=PAGE_SIZE)
    if module == 'shareholders':
        params['source'] = 1
    if module == 'bankruptcy_detail':
        if not detail_id:
            return {'state': 'failed', 'message': '缺少案件标识', 'data': None}
        params = {'gid': keyword, 'uuid': detail_id}
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False) as client:
            response = client.get(url + ENDPOINTS[module][2], params=params, headers={'Authorization': token})
        if response.status_code != 200:
            return {'state': 'failed', 'message': f'数据服务返回 HTTP {response.status_code}，请稍后重试', 'data': None}
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError('invalid envelope')
        raw_code = body.get('error_code')
        code = int(raw_code) if isinstance(raw_code, (int, str)) and str(raw_code).isdigit() else None
        if code != 0:
            state, message = ERRORS.get(code, ('failed', '数据服务查询失败，请重试'))
            # No result on later pages must not erase an earlier positive count.
            if state == 'empty' and module in PAGED and page > 1:
                state, message = 'failed', '分页记录已变化，请更新该项后重新查询'
            data = {'total': 0, 'items': [], 'records': []} if state == 'empty' and module in PAGED else None
            return {'state': state, 'message': message, 'data': data, 'provider_code': code}
        data = body.get('result')
        if data is None:
            raise ValueError('missing result')
        if module == 'basic':
            if not isinstance(data, dict) or not data.get('name') or not data.get('id'):
                raise ValueError('invalid identity')
            data['id'] = str(data['id'])
        if module in PAGED:
            if not isinstance(data, dict) or not isinstance(data.get('items'), list) or type(data.get('total')) is not int or data['total'] < 0:
                raise ValueError('invalid page')
            if not all(isinstance(x, dict) for x in data['items']):
                raise ValueError('invalid rows')
            if len(data['items']) > PAGE_SIZE or len(data['items']) > data['total'] or (data['total'] > 0 and not data['items']):
                raise ValueError('inconsistent count')
            if page > 1 and data['total'] == 0:
                raise ValueError('empty later page')
            if module in RISKS:
                data['records'] = [record(module, x) for x in data['items']]
            if 'gid' in data:
                data['gid'] = str(data['gid'])
        if module == 'ownership' and (not isinstance(data, dict) or type(data.get('companyType')) is not int):
            raise ValueError('invalid ownership')
        if module == 'scale' and (not isinstance(data, str) or not data.strip()):
            raise ValueError('invalid scale')
        if module == 'bankruptcy_detail':
            if not isinstance(data, dict) or str(data.get('uuid')) != detail_id:
                raise ValueError('invalid case detail')
            data['record'] = record(module, data)
        empty = module in PAGED and data['total'] == 0
        return {'state': 'empty' if empty else 'ready', 'message': '本次查询未发现相关记录' if empty else '', 'data': data, 'provider_code': 0}
    except (httpx.HTTPError, ValueError, TypeError):
        return {'state': 'failed', 'message': '数据服务暂时无法访问或返回格式异常，请重试', 'data': None}
