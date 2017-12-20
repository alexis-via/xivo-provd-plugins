# -*- coding: utf-8 -*-

# Copyright 2017 The Wazo Authors  (see the AUTHORS file)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>

import logging
import re
import os.path
from provd import plugins
from provd import tzinform
from provd import synchronize
from provd.devices.config import RawConfigError
from provd.devices.pgasso import IMPROBABLE_SUPPORT, PROBABLE_SUPPORT,\
    COMPLETE_SUPPORT, FULL_SUPPORT, BasePgAssociator
from provd.plugins import StandardPlugin, FetchfwPluginHelper,\
    TemplatePluginHelper
from provd.servers.http import HTTPNoListingFileService
from provd.util import norm_mac, format_mac
from twisted.internet import defer, threads

logger = logging.getLogger('plugin.wazo-htek')


class BaseHtekHTTPDeviceInfoExtractor(object):
    _UA_REGEX_LIST = [
        re.compile(r'^Htek ([^ ]+) ([^ ]+) ([^ ]+)$')
    ]

    def extract(self, request, request_type):
        return defer.succeed(self._do_extract(request))

    def _do_extract(self, request):
        ua = request.getHeader('User-Agent')
        if ua:
            return self._extract_from_ua(ua)

    def _extract_from_ua(self, ua):
        # HTTP User-Agent:
        #   "Htek UC903 2.0.4.2 00:1f:c1:1c:22:a9"

        for UA_REGEX in self._UA_REGEX_LIST:
            m = UA_REGEX.match(ua)
            if m:
                raw_model, raw_version, raw_mac = m.groups()
                try:
                    mac = norm_mac(raw_mac.decode('ascii'))
                except ValueError as e:
                    logger.warning('Could not normalize MAC address "%s": %s', raw_mac, e)
                    return {u'vendor': u'Htek',
                            u'model': raw_model.decode('ascii'),
                            u'version': raw_version.decode('ascii')}
                else:
                    return {u'vendor': u'Htek',
                            u'model': raw_model.decode('ascii'),
                            u'version': raw_version.decode('ascii'),
                            u'mac': mac}
        return None


class BaseHtekPgAssociator(BasePgAssociator):
    def __init__(self, model_versions):
        # model_versions is a dictionary which keys are model IDs and values
        # are version IDs.
        BasePgAssociator.__init__(self)
        self._model_versions = model_versions

    def _do_associate(self, vendor, model, version):
        if vendor == u'Htek':
            if model in self._model_versions:
                if version == self._model_versions[model]:
                    return FULL_SUPPORT
                return COMPLETE_SUPPORT
            return PROBABLE_SUPPORT
        return IMPROBABLE_SUPPORT


class BaseHtekFunckeyGenerator(object):

    def __init__(self, device, raw_config):
        self._model = device.get(u'model')
        self._exten_pickup_call = raw_config.get(u'exten_pickup_call')
        self._funckeys = raw_config[u'funckeys']
        self._lines = []

    def generate(self):
        prefixes = BaseHtekFunckeyPrefixIterator(self._model)
        for funckey_no, prefix in enumerate(prefixes, start=1):
            funckey = self._funckeys.get(unicode(funckey_no))
            self._format_funckey(prefix, funckey_no, funckey)
            self._lines.append(u'')

        return u'\n'.join(self._lines)

    def _format_funckey(self, prefix, funckey_no, funckey):
        if funckey is None:
            if funckey_no == 1 and self._model == u'T46G':
                self._format_funckey_line(prefix)
            else:
                self._format_funckey_null(prefix)
            return

        funckey_type = funckey[u'type']
        if funckey_type == u'speeddial':
            self._format_funckey_speeddial(prefix, funckey)
        elif funckey_type == u'blf':
            self._format_funckey_blf(prefix, funckey)
        elif funckey_type == u'park':
            self._format_funckey_park(prefix, funckey)
        else:
            logger.info('Unsupported funckey type: %s', funckey_type)

    def _format_funckey_null(self, prefix):
        self._lines.append(u'%s.type = %%NULL%%' % prefix)
        self._lines.append(u'%s.line = %%NULL%%' % prefix)
        self._lines.append(u'%s.value = %%NULL%%' % prefix)
        self._lines.append(u'%s.label = %%NULL%%' % prefix)

    def _format_funckey_speeddial(self, prefix, funckey):
        self._lines.append(u'%s.type = 13' % prefix)
        self._lines.append(u'%s.line = %s' % (prefix, funckey.get(u'line', 1)))
        self._lines.append(u'%s.value = %s' % (prefix, funckey[u'value']))
        self._lines.append(u'%s.label = %s' % (prefix, funckey.get(u'label', u'')))

    def _format_funckey_park(self, prefix, funckey):
        self._lines.append(u'%s.type = 10' % prefix)
        self._lines.append(u'%s.line = %s' % (prefix, funckey.get(u'line', 1)))
        self._lines.append(u'%s.value = %s' % (prefix, funckey[u'value']))
        self._lines.append(u'%s.label = %s' % (prefix, funckey.get(u'label', u'')))

    def _format_funckey_blf(self, prefix, funckey):
        line_no = funckey.get(u'line', 1)
        if self._model in (u'T32G', u'T38G'):
            line_no -= 1
        self._lines.append(u'%s.type = 16' % prefix)
        self._lines.append(u'%s.line = %s' % (prefix, line_no))
        self._lines.append(u'%s.value = %s' % (prefix, funckey[u'value']))
        self._lines.append(u'%s.label = %s' % (prefix, funckey.get(u'label', u'')))
        if self._exten_pickup_call:
            self._lines.append(u'%s.pickup_value = %s' % (prefix, self._exten_pickup_call))

    def _format_funckey_line(self, prefix):
        self._lines.append(u'%s.type = 15' % prefix)
        self._lines.append(u'%s.line = 1' % prefix)
        self._lines.append(u'%s.value = %%NULL%%' % prefix)
        self._lines.append(u'%s.label = %%NULL%%' % prefix)


class BaseHtekFunckeyPrefixIterator(object):

    _NB_LINEKEY = {
        u'T40P': 3,
    }
    _NB_MEMORYKEY = {
        u'T48S': 0,
    }
    _NB_EXPMODKEY = 40

    def __init__(self, model):
        self._nb_linekey = self._nb_linekey_by_model(model)
        self._nb_memorykey = self._nb_memorykey_by_model(model)
        self._nb_expmod = self._nb_expmod_by_model(model)

    def _nb_linekey_by_model(self, model):
        if model is None:
            logger.info('No model information; no linekey will be configured')
            return 0
        nb_linekey = self._NB_LINEKEY.get(model)
        if nb_linekey is None:
            logger.info('Unknown model %s; no linekey will be configured', model)
            return 0
        return nb_linekey

    def _nb_memorykey_by_model(self, model):
        if model is None:
            logger.info('No model information; no memorykey will be configured')
            return 0
        nb_memorykey = self._NB_MEMORYKEY.get(model)
        if nb_memorykey is None:
            logger.info('Unknown model %s; no memorykey will be configured', model)
            return 0
        return nb_memorykey

    def _nb_expmod_by_model(self, model):
        if model in (u'T27P', u'T27G', u'T29G', u'T46G', u'T46S', u'T48G', u'T48S'):
            return 6
        else:
            return 0

    def __iter__(self):
        for linekey_no in xrange(1, self._nb_linekey + 1):
            yield u'linekey.%s' % linekey_no
        for memorykey_no in xrange(1, self._nb_memorykey + 1):
            yield u'memorykey.%s' % memorykey_no
        for expmod_no in xrange(1, self._nb_expmod + 1):
            for expmodkey_no in xrange(1, self._NB_EXPMODKEY + 1):
                yield u'expansion_module.%s.key.%s' % (expmod_no, expmodkey_no)


class BaseHtekPlugin(StandardPlugin):
    _ENCODING = 'UTF-8'
    _LOCALE = {
        u'de_DE': (u'German', u'Germany', u'2'),
        u'en_US': (u'English', u'United States', u'0'),
        u'es_ES': (u'Spanish', u'Spain', u'6'),
        u'fr_FR': (u'French', u'France', u'1'),
        u'fr_CA': (u'French', u'United States', u'1'),
    }
    _SIP_DTMF_MODE = {
        u'RTP-in-band': u'0',
        u'RTP-out-of-band': u'1',
        u'SIP-INFO': u'2',
    }
    _SIP_TRANSPORT = {
        u'udp': u'0',
        u'tcp': u'1',
        u'tls': u'2',
    }
    _SIP_TRANSPORT_DEF = u'0'
    _NB_SIP_ACCOUNTS = {
        u'T48S': 16,
    }

    def __init__(self, app, plugin_dir, gen_cfg, spec_cfg):
        StandardPlugin.__init__(self, app, plugin_dir, gen_cfg, spec_cfg)

        self._tpl_helper = TemplatePluginHelper(plugin_dir)

        downloaders = FetchfwPluginHelper.new_downloaders(gen_cfg.get('proxies'))
        fetchfw_helper = FetchfwPluginHelper(plugin_dir, downloaders)

        self.services = fetchfw_helper.services()
        self.http_service = HTTPNoListingFileService(self._tftpboot_dir)

    http_dev_info_extractor = BaseHtekHTTPDeviceInfoExtractor()

    def configure_common(self, raw_config):
        for filename, fw_filename, tpl_filename in self._COMMON_FILES:
            tpl = self._tpl_helper.get_template('common/%s' % tpl_filename)
            dst = os.path.join(self._tftpboot_dir, filename)
            raw_config[u'XX_fw_filename'] = fw_filename
            self._tpl_helper.dump(tpl, raw_config, dst, self._ENCODING)

    def _update_sip_lines(self, raw_config):
        for line_no, line in raw_config[u'sip_lines'].iteritems():
            # set line number
            line[u'XX_line_no'] = int(line_no)
            # set dtmf inband transfer
            dtmf_mode = line.get(u'dtmf_mode') or raw_config.get(u'sip_dtmf_mode')
            if dtmf_mode in self._SIP_DTMF_MODE:
                line[u'XX_dtmf_type'] = self._SIP_DTMF_MODE[dtmf_mode]
            # set voicemail
            if u'voicemail' not in line and u'exten_voicemail' in raw_config:
                line[u'voicemail'] = raw_config[u'exten_voicemail']
            # set proxy_ip
            if u'proxy_ip' not in line:
                line[u'proxy_ip'] = raw_config[u'sip_proxy_ip']
            # set proxy_port
            if u'proxy_port' not in line and u'sip_proxy_port' in raw_config:
                line[u'proxy_port'] = raw_config[u'sip_proxy_port']

    def _add_fkeys(self, device, raw_config):
        funckey_generator = BaseHtekFunckeyGenerator(device, raw_config)
        raw_config[u'XX_fkeys'] = funckey_generator.generate()

    def _add_country_and_lang(self, raw_config):
        locale = raw_config.get(u'locale')
        if locale in self._LOCALE:
            (raw_config[u'XX_lang'],
             raw_config[u'XX_country'],
             raw_config[u'XX_handset_lang']) = self._LOCALE[locale]

    def _format_dst_change(self, dst_change):
        if dst_change['day'].startswith('D'):
            return u'%02d/%02d/%02d' % (dst_change['month'], int(dst_change['day'][1:]), dst_change['time'].as_hours)
        else:
            week, weekday = map(int, dst_change['day'][1:].split('.'))
            weekday = tzinform.week_start_on_monday(weekday)
            return u'%d/%d/%d/%d' % (dst_change['month'], week, weekday, dst_change['time'].as_hours)

    def _format_tz_info(self, tzinfo):
        lines = []
        lines.append(u'local_time.time_zone = %+d' % min(max(tzinfo['utcoffset'].as_hours, -11), 12))
        if tzinfo['dst'] is None:
            lines.append(u'local_time.summer_time = 0')
        else:
            lines.append(u'local_time.summer_time = 1')
            if tzinfo['dst']['start']['day'].startswith('D'):
                lines.append(u'local_time.dst_time_type = 0')
            else:
                lines.append(u'local_time.dst_time_type = 1')
            lines.append(u'local_time.start_time = %s' % self._format_dst_change(tzinfo['dst']['start']))
            lines.append(u'local_time.end_time = %s' % self._format_dst_change(tzinfo['dst']['end']))
            lines.append(u'local_time.offset_time = %s' % tzinfo['dst']['save'].as_minutes)
        return u'\n'.join(lines)

    def _add_timezone(self, raw_config):
        if u'timezone' in raw_config:
            try:
                tzinfo = tzinform.get_timezone_info(raw_config[u'timezone'])
            except tzinform.TimezoneNotFoundError, e:
                logger.warning('Unknown timezone: %s', e)
            else:
                raw_config[u'XX_timezone'] = self._format_tz_info(tzinfo)

    def _add_sip_transport(self, raw_config):
        raw_config[u'XX_sip_transport'] = self._SIP_TRANSPORT.get(raw_config.get(u'sip_transport'),
                                                                  self._SIP_TRANSPORT_DEF)

    def _add_xx_sip_lines(self, device, raw_config):
        sip_lines = raw_config[u'sip_lines']
        sip_accounts = self._get_sip_accounts(device.get(u'model'))
        if not sip_accounts:
            xx_sip_lines = dict(sip_lines)
        else:
            xx_sip_lines = {}
            for line_no in xrange(1, sip_accounts + 1):
                line_no = str(line_no)
                xx_sip_lines[line_no] = sip_lines.get(line_no)
        raw_config[u'XX_sip_lines'] = xx_sip_lines

    def _get_sip_accounts(self, model):
        return self._NB_SIP_ACCOUNTS.get(model)

    def _add_xivo_phonebook_url(self, raw_config):
        if hasattr(plugins, 'add_xivo_phonebook_url') and raw_config.get(u'config_version', 0) >= 1:
            plugins.add_xivo_phonebook_url(raw_config, u'yealink', entry_point=u'lookup', qs_suffix=u'term=#SEARCH')
        else:
            self._add_xivo_phonebook_url_compat(raw_config)

    def _add_xivo_phonebook_url_compat(self, raw_config):
        hostname = raw_config.get(u'X_xivo_phonebook_ip')
        if hostname:
            raw_config[u'XX_xivo_phonebook_url'] = u'http://{hostname}/service/ipbx/web_services.php/phonebook/search/?name=#SEARCH'.format(hostname=hostname)

    _SENSITIVE_FILENAME_REGEX = re.compile(r'^[0-9a-f]{12}\.cfg')

    def _dev_specific_filename(self, device):
        # Return the device specific filename (not pathname) of device
        fmted_mac = format_mac(device[u'mac'], separator='')
        return fmted_mac + '.cfg'

    def _check_config(self, raw_config):
        if u'http_port' not in raw_config:
            raise RawConfigError('only support configuration via HTTP')

    def _check_device(self, device):
        if u'mac' not in device:
            raise Exception('MAC address needed for device configuration')

    def configure(self, device, raw_config):
        self._check_config(raw_config)
        self._check_device(device)
        filename = self._dev_specific_filename(device)
        tpl = self._tpl_helper.get_dev_template(filename, device)

        self._add_fkeys(device, raw_config)
        self._add_country_and_lang(raw_config)
        self._add_timezone(raw_config)
        self._add_sip_transport(raw_config)
        self._update_sip_lines(raw_config)
        self._add_xx_sip_lines(device, raw_config)
        self._add_xivo_phonebook_url(raw_config)
        raw_config[u'XX_options'] = device.get(u'options', {})

        path = os.path.join(self._tftpboot_dir, filename)
        self._tpl_helper.dump(tpl, raw_config, path, self._ENCODING)

    def deconfigure(self, device):
        path = os.path.join(self._tftpboot_dir, self._dev_specific_filename(device))
        try:
            os.remove(path)
        except OSError, e:
            # ignore
            logger.info('error while removing file: %s', e)

    if hasattr(synchronize, 'standard_sip_synchronize'):
        def synchronize(self, device, raw_config):
            return synchronize.standard_sip_synchronize(device)

    else:
        # backward compatibility with older xivo-provd server
        def synchronize(self, device, raw_config):
            try:
                ip = device[u'ip'].encode('ascii')
            except KeyError:
                return defer.fail(Exception('IP address needed for device synchronization'))
            else:
                sync_service = synchronize.get_sync_service()
                if sync_service is None or sync_service.TYPE != 'AsteriskAMI':
                    return defer.fail(Exception('Incompatible sync service: %s' % sync_service))
                else:
                    return threads.deferToThread(sync_service.sip_notify, ip, 'check-sync')

    def get_remote_state_trigger_filename(self, device):
        if u'mac' not in device:
            return None

        return self._dev_specific_filename(device)

    def is_sensitive_filename(self, filename):
        return bool(self._SENSITIVE_FILENAME_REGEX.match(filename))
