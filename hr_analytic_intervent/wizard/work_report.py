# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2001-2014 Micronaet SRL (<http://www.micronaet.it>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from openerp.osv import fields,osv
import os
from datetime import datetime, timedelta


class hr_timesheet_work_journal_wizarp(osv.osv_memory):
    ''' Wizard for filter intervet in work journal
    '''
    _name = "hr.timesheet.work.journal.wizard"
    _description = "Wizard open work journal"

    # --------------
    # Wizard button:
    # --------------
    def action_open_report(self, cr, uid, ids, context=None):
        ''' Open report
        '''
        if context is None: 
            context={}        
        data = {}
        wiz_proxy = self.browse(cr, uid, ids, context=context)[0]
        
        data['from_date'] = wiz_proxy.from_date or False
        data['to_date'] = wiz_proxy.to_date or False
        data['account_id'] = wiz_proxy.account_id.id or False
        data['type'] = wiz_proxy.type
        data['summary'] = wiz_proxy.summary
        
        return {
            'type': 'ir.actions.report.xml', 
            'report_name':'hr_intervent_registry',        
            'datas': data,
            }

    # ---------------
    # Field function:
    # ---------------
    def get_default_date(self, cr, uid, field, context=None):
        ''' Set default element (first/last of the month)
        '''
        if field == 'from_date':
            return datetime.now().strftime("%Y-%m-01")
        return datetime.now().strftime("%Y-%m-30")
    
    _columns = {
        'from_date': fields.date('From date', required=True),
        'to_date': fields.date('To date', required=True),        
        'account_id': fields.many2one('account.analytic.account', 'Account', required=False),
        'summary': fields.boolean('Summary'),
        'type':fields.selection([
            ('only','Only default account'),
            ('economy','Only economy'),
            ('all','All (default and economy)'),            
        ],'Type', select=True, readonly=False, required=True),
    }           
    
    _defaults = {
        'from_date': lambda s, cr, uid, ctx: s.get_default_date(
            cr, uid, 'from_date', ctx),
        'to_date': lambda s, cr, uid, ctx: s.get_default_date(
            cr, uid, 'to_date', ctx),
        'type': lambda *x: 'all',
        'summary': lambda *x: True,
    }
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
