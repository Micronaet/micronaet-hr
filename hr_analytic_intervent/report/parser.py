# -*- coding: utf-8 -*-
###############################################################################
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
###############################################################################
import os
import sys
import openerp.netsvc
import logging
from openerp.report import report_sxw
from openerp.report.report_sxw import rml_parse
from openerp.osv import osv, fields
from datetime import datetime, timedelta
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, DATETIME_FORMATS_MAP, float_compare
import openerp.addons.decimal_precision as dp
from openerp.tools.translate import _


_logger = logging.getLogger(__name__)

translate = {
    1: u"Lunedì",
    2: u"Martedì",
    3: u"Mercoledì",
    4: u"Giovedì",
    5: u"Venerdì",
    6: u"Sabato",                   
    7: u"Domenica",
}

class Parser(report_sxw.rml_parse):
    # Summary totalizator
    employee_list = {}
    summary_user = {}
    summary_cost = {}
    
    def __init__(self, cr, uid, name, context):
        super(Parser, self).__init__(cr, uid, name, context)
        self.localcontext.update({
            'get_records': self.get_records,
            'load_employee': self.load_employee,
            'get_employee': self.get_employee,
            'get_employee_hour': self.get_employee_hour,
            'get_cost_record': self.get_cost_record,
            'dow': self.dow,
            'get_summary': self.get_summary,
            })

    def get_cost_record(self, material, economy=False): 
        ''' Return record description formatted and save in summary total value        
        '''
        if material.product_id.id not in self.summary_cost:
            self.summary_cost[material.product_id.id] = [
                "%s %s" % (
                    material.product_id.name,
                    material.product_id.uom_id.name if material.product_id.uom_id else " ",),
                0.0, # work
                0.0, # economy
                ]
        if economy:        
            self.summary_cost[material.product_id.id][2] += material.product_qty or 0.0
        else:    
            self.summary_cost[material.product_id.id][1] += material.product_qty or 0.0

        _logger.info("Work: %s q: %s pr. %s (%s)" % (
            material.product_id.name,
            material.product_qty,
            self.summary_cost[material.product_id.id][2] if economy else self.summary_cost[material.product_id.id][1],
            "E" if economy else "W",
            ))

        return "%s %s %s%s\n" % (
            material.product_qty or 0.0, 
            material.product_id.uom_id.name if material.product_id.uom_id else " X ",
            material.product_id.name,
            "(E)" if economy else "",
            )
        
    def get_summary(self, summary_type):
        ''' Return summary dictionary:
            summary_type: 'user', 'cost'
        '''
        if summary_type == 'user':
            return self.summary_user
        elif summary_type == 'cost':
            return self.summary_cost
        else:
            return {}
           

    def dow(self, date):
        ''' Day of week from date ISO format
        '''
        from datetime import datetime 
        try:
            return translate[datetime.strptime(date, "%Y-%m-%d").isoweekday()]
        except:    
            return "Non identificabile"
        
    def load_employee(self, ):
        ''' Executed ad the begin of the report
            reset values and load correct
        '''        
        # Reset also summary:
        self.summary_user = {}
        self.summary_cost = {}
        
        employee_pool = self.pool.get('hr.employee')
        employee_ids = employee_pool.search(
            self.cr, self.uid, [], order='short_name')
        employee_proxy = employee_pool.browse(self.cr, self.uid, employee_ids)
        self.employee_list = {}  # reset dict
        i = 0
        for employee in employee_proxy:
            if employee.user_id and employee.user_id.registry_user: 
                self.employee_list[i] = employee.user_id.short_name
                
                self.summary_user[i] = [0.0, 0.0] # [work, economy]
                i += 1

        return     

    def get_employee(self, position):
        ''' Get N position of employee (if present)
            position are from 0 to max col (actually 13) of report
        '''
        return self.employee_list.get(position, "").upper()

    def get_employee_hour(self, o, position, data=None, economy=False):
        ''' Read hour for employee in position passed for record o
        '''
        if data is None:
            data = {}
        try:
            tot = 0.0
            for employee in o.employee_ids:            
                if employee.line_id.user_id.short_name == self.employee_list[position]:
                    data_filter = data.get('type', 'all')
                    if economy:
                        if data_filter in ('all', 'economy') and employee.extra_invoice:
                            tot += employee.unit_amount or 0.0
                            self.summary_user[position][1] += employee.unit_amount or 0.0
                    else: # work
                        if data_filter in ('all', 'only') and not employee.extra_invoice:
                            tot += employee.unit_amount or 0.0
                            self.summary_user[position][0] += employee.unit_amount or 0.0

        except:
            return "" #"ERR!"
        return tot if tot else ""
        
    def get_records(self, data=None, context=None):
        ''' Print registry 
            TODO selected record or all
        '''
        account_pool = self.pool.get('account.analytic.account')
        intervent_pool = self.pool.get('hr.analytic.timesheet.intervent')

        if data is None:
            data = {}
            
        # Create domain according to wizard:    
        domain = []
        if 'from_date' in data:
            domain.append(('date', '>=', data['from_date']))
        if 'to_date' in data:
            domain.append(('date', '<=', data['to_date']))

        account_id = data.get('account_id', False)
        if account_id:
            account_ids = account_pool.search(self.cr, self.uid, [
                ('parent_id', '=', account_id)])
            account_ids.append(account_id)    
            domain.append(('account_id', 'in', account_ids))            

        intervent_ids = intervent_pool.search(
            self.cr, self.uid, domain, order='date')
        return intervent_pool.browse(self.cr, self.uid, intervent_ids)

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
