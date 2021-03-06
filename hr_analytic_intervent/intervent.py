# -*- coding: utf-8 -*-
###############################################################################
#
# OpenERP, Open Source Management Solution
# Copyright (C) 2001-2015 Micronaet S.r.l. (<http://www.micronaet.it>)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

import os
import sys
import logging
import openerp
import openerp.netsvc as netsvc
import openerp.addons.decimal_precision as dp
from openerp.osv import fields, osv, expression, orm
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from openerp import SUPERUSER_ID, api
from openerp import tools
from openerp.tools.translate import _
from openerp.tools.float_utils import float_round as round
from openerp.tools import (DEFAULT_SERVER_DATE_FORMAT, 
    DEFAULT_SERVER_DATETIME_FORMAT, 
    DATETIME_FORMATS_MAP, 
    float_compare)


_logger = logging.getLogger(__name__)

class account_analytic_account_pricelist(orm.Model):
    """ Pricelist for analytic account
    """    
    
    _name = 'account.analytic.account.pricelist'
    _description = 'Analytic account pricelist'
    _rec_name = 'product_id'
    
    # ----------------
    # On change event:
    # ----------------
    def onchange_product(self, cr, uid, ids, product_id, context=None):
        ''' Find cost
        '''
        res = {}
        if not product_id:
            return res
        
        product_proxy = self.pool.get('product.product').browse(
            cr, uid, product_id, context=context)
        res['value'] = {}
        res['value']['cost'] = product_proxy.standard_price or False
        return res

    _columns = {
        'product_id':fields.many2one('product.product', 'Product', 
            required=True),
        'cost': fields.float("Cost", help="Unit Cost for this product line", 
            digits_compute=dp.get_precision('Product Price'), required=True),
        'product_uom': fields.related('product_id', 'uom_id', type='many2one',
            relation = 'product.uom', string = 'UOM'),
        'account_id': fields.many2one('account.analytic.account', 'Account', 
            required=False),
    }

class account_analytic_account(orm.Model):
    """ Add fields for manage economy works
    """    
    
    _inherit = 'account.analytic.account'

    def get_code(self, cr, uid, name, parent_id, contract, economy, 
            context=None):
        ''' Utility for create code depend on name:
        '''
        if contract or economy: # change name with parent one's
            if parent_id:
                name = self.browse(cr, uid, parent_id, context=context).name
            else:    
                return False # no parent (error)

        if name[2:3] == '-':            
            return "%s%s%s" % (
                name.split(" ")[0][0:8],
                ".C" if contract else "",
                ".E" if economy else "",
                )
        return False
    # ------------------
    # Override function:
    # ------------------
    def write(self, cr, uid, ids, vals, context=None):
        """
        Update redord(s) comes in {ids}, with new value comes as {vals}
        return True on success, False otherwise
    
        @param cr: cursor to database
        @param uid: id of current user
        @param ids: list of record ids to be update
        @param vals: dict of new values to be set
        @param context: context arguments, like lang, time zone
        
        @return: True on success, False otherwise
        """
        # Force code in name is in style "AA-NNN Customer"
        previous_proxy = self.browse(cr, uid, ids, context=context)[0]

        code = self.get_code(cr, uid,
            vals.get('name', previous_proxy.name),
            vals.get('parent_id', previous_proxy.parent_id.id),
            vals.get('contract', previous_proxy.contract or False),
            vals.get('economy', previous_proxy.economy or False),
            context=context,
            )
        if code:
            vals['code'] = code
            
        return super(account_analytic_account, self).write(
            cr, uid, ids, vals, context=context)
    
    def create(self, cr, uid, vals, context=None):
        """
        Create a new record for a model ModelName
        @param cr: cursor to database
        @param uid: id of current user
        @param vals: provides a data for new record
        @param context: context arguments, like lang, time zone
        
        @return: returns a id of new record
        
        When create an account check if is a contract, in this case create
        subaccount contract and economy 
        """
        # Check if there's a syntax: "YY-NNN Customer"
        #print "Create", vals['name']
        contract = vals.get('contract', False)
        economy = vals.get('economy', False)
        code = self.get_code(cr, uid,
            vals['name'], 
            vals.get('parent_id', False), 
            contract,
            economy, 
            context=context,
            )
        if code: 
            vals['code'] = code
                
        parent_id = super(account_analytic_account, self).create(
            cr, uid, vals, context=context)

        # if code then is contract, if force_child then create by journal
        # economy or contract is for not loop during creation
        if (context.get('force_child', False) or code) and not (
                contract or economy):
            # Create child:
            if 'partner_id' not in vals:
                return # TODO error!!!
                
            partner_proxy = self.pool.get('res.partner').browse(
                cr, uid, vals.get('partner_id'), context=context)

            # Create contract:
            self.create(cr, uid, {
                'partner_id': partner_proxy.id,
                'type': 'normal',
                'parent_id': parent_id,
                'use_timesheets': True,
                'pricelist_id': 
                    partner_proxy.property_product_pricelist \
                    and partner_proxy.property_product_pricelist.id \
                    or False,
                'economy': False,
                'contract': True,
                'name': _("Contract")
                }, context=context)
            # Create economy
            self.create(cr, uid, {
                'partner_id': partner_proxy.id,
                'type': 'normal',
                'parent_id': parent_id,
                'use_timesheets': True,
                'pricelist_id': 
                    partner_proxy.property_product_pricelist \
                    and partner_proxy.property_product_pricelist.id \
                    or False,
                'economy': True,    
                'contract': False,
                'name': _("Economy")
                }, context=context)
                
            return parent_id
    
    # ---------------
    # Field function:
    # ---------------
    def _remain_total(self, cr, uid, ids, field, args, context=None):
        ''' Diference between total of account and invoiced
        '''
        res = {}
        for item in self.browse(cr, uid, ids, context=context):
            if item.account_total:
                res[item.id] = 100.0 * (item.debit or 0.0) / (item.account_total)
            else:
                res[item.id] = 0.0 # no value if not account_total present    
        return res
        
    _columns = {
        'economy': fields.boolean('Economy'),
        'contract': fields.boolean('Contract'),
        'account_total': fields.float('Total', digits=(16, 2)),
        'total_progress': fields.function(_remain_total, method=True, type='float', string='Invoiced', store=False, help='Invoice value on total'),    
        'pricelist': fields.boolean('Have pricelist', required=False, help='This account have a custom pricelist'),
        'pricelist_ids':fields.one2many('account.analytic.account.pricelist', 'account_id', 'Pricelist', required=False),
    }
    
    _defaults = {
        'economy': lambda *x: False,
        'contract': lambda *x: False,
        'pricelist': lambda *a: False,
    }

class res_users(orm.Model):
    ''' Extra field for users
    '''
    
    _inherit = 'res.users'
    
    _columns = {
        'registry_user': fields.boolean('User in registry', help = 'If the user is in the registry columns'),
        'short_name': fields.char('Ref. in registry', size = 15, required = False, help = 'Short name in registry column (if not present short name no column in report for this user)'),        
    }
    
class hr_employee(orm.Model):
    ''' Extra field for employee
    '''
    
    _inherit = 'hr.employee'
    
    _columns = {
        'registry_user': fields.related('user_id', 'registry_user', 
            type='boolean', string='User in registry', store = True, 
            help = 'If the user is in the registry columns'),        
        'short_name': fields.related('user_id', 'short_name', type='char', 
            string='Ref. in registry', store = True, 
            help = 'Short name in registry column (if not present short name no column in report for this user)'),        
    }

class hr_analytic_timesheet_intervent_weather(orm.Model):
    ''' Weather conditions 
    '''
    
    _name = 'hr.analytic.timesheet.intervent.weather'
    _description = 'Analytic Intervent weather'
    
    _columns = {
        'name': fields.char('Description', size=40, required=True),
        'note': fields.text('Annotations'),
    }

class hr_analytic_timesheet_intervent(orm.Model):
    ''' Intervent that is create as a parent for:
        1. List of stock.move for material used during intervent
        2. List of hr.employee that work for the analytic account
        3. Extra information like journal
    '''
    
    _name = 'hr.analytic.timesheet.intervent'
    _description = 'Analytic Intervent'
    _rec_name = 'date'

    # -------------------------------------------------------------------------
    #                            ORM Method
    # -------------------------------------------------------------------------
    def unlink(self, cr, uid, ids, context=None):
        """
        Delete all record(s) from table heaving record id in ids
        return True on success, False otherwise 
    
        @param cr: cursor to database
        @param uid: id of current user
        @param ids: list of record ids to be removed from table
        @param context: context arguments, like lang, time zone
        
        @return: True on success, False otherwise
        """  
        
        # -------------------------------------------------
        # Delete before all intervent and analytic account:
        # -------------------------------------------------
        ts_pool = self.pool.get('hr.analytic.timesheet')
        move_pool = self.pool.get('stock.move')

        delete_intervent_ids = []
        delete_move_ids = []
        
        for intervent in self.browse(cr, uid, ids, context=context):
            # -------------------------------
            # Delete analytic line intervent:
            # -------------------------------
            for ts in intervent.employee_ids:
                delete_intervent_ids.append(ts.id)

            # -----------------
            # Delete stock.move
            # -----------------
            for move in intervent.move_ids:
                delete_move_ids.append(move.id)
            
        ts_pool.unlink(cr, uid, delete_intervent_ids, context=context)
        move_pool.unlink(cr, uid, delete_move_ids, context=context)
        # raise osv.except_osv(_('Invalid Action!'), 
        #_('In order to delete a confirmed sales order, cancel it before!'))
        
        # ------------------------------------
        # Than delete intervent parent record:
        # ------------------------------------
        return orm.Model.unlink(self, cr, uid, ids, context=context)
        
    # -------------------------------------------------------------------------
    #                            On change function
    # -------------------------------------------------------------------------
    def onchange_partner_id(self, cr, uid, ids, partner_id, context=None):
        ''' Set acount domain depend on partner
        '''
        res = {}
        res['value'] = {}
        res['domain'] = {}
        res['value']['account_id'] = False

        if partner_id:
            res['domain']['account_id'] = [
                ('type', '=', 'view'),
                ('use_timesheets', '=', False),
                ('partner_id', '=', partner_id),
                ]
        else:
            res['domain']['account_id'] = [
                ('type', '=', 'view'),
                ('use_timesheets', '=', False)
                ]
        return res

    # -------------------------------------------------------------------------
    #                                Field
    # -------------------------------------------------------------------------
    _columns = {
        'date': fields.date('Date', required = True),
        'name': fields.text('Annotations', 
            help='Annotations, special and general'),
        'economy_note': fields.text('Economy annotations', 
            help='Annotations for economy work, special and general'),
        'note': fields.text('Observation', 
            help = 'Observation and instruction of team manager'),
        'economy_observation': fields.text('Economy observation', 
            help='Observation for economy work'),
        'weather_id':fields.many2one('hr.analytic.timesheet.intervent.weather',
            'Weather', required = False),
        'default_hour': fields.integer('Default hour', required = False),
        #'invoice_intervent': fields.boolean('Intervent to invoice', required = False, 
        #    help = 'If the intervent is to be invoiced, used for filter elements'),
        'invoice_costs': fields.boolean('Cost to invoice', required = False, 
            help = 'If the costs are to be invoiced, used for filter elements'),
        'partner_id': fields.many2one(
            'res.partner', 'Partner', required = True),
        'account_id': fields.many2one(
            'account.analytic.account', 'Account analytic', 
            required = True, help = 'Account analytic, contract, construction',),

        #'state':fields.selection([
        #    ('draft', 'Draft'),                    # Draft intervent
        #    ('cancel', 'Cancelled'),               # Intervent cancel
        #    ('confirmed', 'Confirmed'),            # Intervent confirmed
        #],'State', select=True, readonly=True),    
    }
    
    _defaults = {
        'date': lambda *x: datetime.today().strftime(DEFAULT_SERVER_DATE_FORMAT),
        'default_hour': lambda *x: 8,
        #'state': lambda *a: 'draft',        
    }

class stock_move(orm.Model):
    ''' List of cost linked to intervent TODO replare cost
    '''
    
    _inherit = 'stock.move'
    
    # ------------------
    # Override function:
    # ------------------
    def create(self, cr, uid, vals, context=None):
        """
        Create a new record for a model ModelName
        @param cr: cursor to database
        @param uid: id of current user
        @param vals: provides a data for new record
        @param context: context arguments, like lang, time zone
        
        @return: returns a id of new record
        """
        # Correction according to direction_move combo:
        # true = go out, false = go in
        go_out = vals.get('direction_move', 'out') == 'out' 
        if not go_out: # reverse location (internal > customer in customer > internal)
            (vals['location_dest_id'], vals['location_id']) = (
                vals['location_id'], vals['location_dest_id'])
            vals['type'] = 'in' #vals.get('direction_move', 'out') # override type movement

        vals['locked'] = True # Lock next write
        res_id = super(stock_move, self).create(cr, uid, vals, context)
        
        # Intervent stock.move:
        intervent_id = vals.get('intervent_id', False)
        if intervent_id:
            self.action_done(cr, uid, [res_id], context=context)
    
            # Create analytic element:
            try:
                journal_id = self.pool.get('account.analytic.journal').search(
                    cr, uid, [('type', '=', 'sale'), ], context=context)[0]
            except:
                # raise error no sale journal
                journal_id = False   
                
            line_pool = self.pool.get('account.analytic.line')            
            product_pool = self.pool.get('product.product')
            
            product_id = vals.get('product_id', False) # TODO must exist
            product_proxy = product_pool.browse(
                cr, uid, product_id, context=context)            
            general_account_id = product_proxy.property_account_expense.id \
                or product_proxy.categ_id.property_account_expense_categ.id \
                or False
            company_id = product_proxy.company_id.id 
            unit_amount = vals.get('product_uom_qty', 0.0)
            product_uom_id = vals.get('product_uom', False)
            
            # Create and link analytic line:
            line_id = line_pool.create(cr, uid, {
                'name': vals.get('name', product_proxy.name),
                'account_id': vals.get('account_id', False),
                'date': vals.get('date_expected')[:10],
                'user_id': uid,
                'journal_id': journal_id, 
                'work_journal_intervent_id': intervent_id,
                'product_id': product_id,
                'unit_amount': unit_amount if go_out else -(unit_amount),
                'product_uom_id': product_uom_id,
                'amount': vals.get('cost_unit', 0.0) * unit_amount * (
                    -1 if go_out else +1),
                'general_account_id': general_account_id, 
                'to_invoice': vals.get('to_invoice', False),
            }, context=context)
            
            # update link to new line
            if line_id:
                self.write(cr, uid, res_id, {
                    'analytic_line_id': line_id, }, context=context)

        return res_id

    def unlink(self, cr, uid, ids, context=None):
        """
        Delete all record(s) from table heaving record id in ids
        return True on success, False otherwise 
    
        @param cr: cursor to database
        @param uid: id of current user
        @param ids: list of record ids to be removed from table
        @param context: context arguments, like lang, time zone
        
        @return: True on success, False otherwise
        """  
        
        try:
            # Delete stock movement:
            for item in self.browse(cr, uid, ids, context=context):
                if item.intervent_id:
                    # delete analytic line linked
                    if item.analytic_line_id:
                        self.pool.get('account.analytic.line').unlink(
                            cr, uid, item.analytic_line_id.id, context=context)

                    # Delete without call original method
                    orm.Model.unlink(self, cr, uid, item.id, context=context)                
                else:
                    # Call original method:
                    res = super(stock_move, self).unlink(
                        cr, uid, item.id, context=context)
            return True
        except:
            return False                

    # -------------------
    # On change function:
    # -------------------
    def onchange_extra_invoice(self, cr, uid, ids, extra_invoice, 
            parent_partner_id, parent_account_id, account_id, context=None):
        ''' On change extra invoice check
            Operations quite the same for intervent>use same onchange procedure
        '''
        # Use the same function for intervent:
        return self.pool.get('hr.analytic.timesheet').onchange_extra_invoice(
            cr, uid, ids, extra_invoice, parent_partner_id, parent_account_id, 
            account_id, context=context)

    def onchange_product_id_name(self, cr, uid, ids, product_id, account_id, 
            context=None):
        ''' On change product_id update name
        '''
        
        res = {'value': {'name': 'Product sell', }} # default value if empty

        # ----------------------
        # Define stock locations
        # ----------------------
        stock_pool = self.pool.get('stock.location')
        # >> internal
        stock_ids = stock_pool.search(cr, uid, [
            #('chained_auto_packing', '=', 'manual'),
            ('usage', '=', 'internal'),
        ], context=context)
        res['value']['location_id'] = stock_ids[0] if stock_ids else False 
        # TODO RAISE
        
        # >> customer
        stock_ids = stock_pool.search(cr, uid, [
            #('chained_auto_packing', '=', 'manual'),
            ('usage', '=', 'customer'),
        ], context=context)
        res['value']['location_dest_id'] = stock_ids[0] if stock_ids else False 
        # TODO RAISE
        
        if product_id:
            product_proxy = self.pool.get('product.product').browse(
                cr, uid, product_id, context=context)
            res['value']['name'] = product_proxy.name
            res['value']['product_uom'] = product_proxy.uom_id.id or False            
            cost = product_proxy.standard_price or 0.0 # default
            
            # Search cost in account pricelist (if present)
            if account_id:
                account_proxy = self.pool.get(
                    'account.analytic.account').browse(
                        cr, uid, account_id, context=context)
                if account_proxy.pricelist:
                    for pl in account_proxy.pricelist_ids:
                        if pl.product_id.id == product_id:
                            cost = pl.cost
                            break # end loop
                            
            res['value']['cost_unit'] = cost
        else:
            res['value']['name'] = _("Product sell")
            res['value']['product_uom'] = False
            res['value']['cost_unit'] = 0.0

        return res        
        
    def onchange_force_cost_unit(self, cr, uid, ids, product_id, account_id, 
            force_cost_unit, context=None):
        ''' If change force cost update unit cost else return default cost
        '''
        
        res = {'value': {}}
        if force_cost_unit:
            res['value']['cost_unit'] = force_cost_unit
        else: # search in 
            try:
                res['value']['cost_unit'] = self.onchange_product_id_name(
                    cr, uid, ids, product_id, account_id, context=context)[
                        'value']['cost_unit']
            except:
                res['value']['cost_unit'] = 0.0
        return res 
            
    # -----------------
    # Default function:
    # -----------------    
    def get_default_account_id(self, cr, uid, context=None):
        ''' Call same function in hr.analytic.timesheet (use same logic)
        '''
        return self.pool.get('hr.analytic.timesheet').get_default_account_id(
            cr, uid, context=context)
            
    _columns = {
        'extra_invoice':fields.boolean('To invoice',
            help='Need an extra invoice for costs'),
        'account_id': fields.many2one('account.analytic.account', 
            'Account analytic', required=False, 
            help='Account analytic, contract, construction',),
        'analytic_line_id': fields.many2one('account.analytic.line', 
            'Analytic line link', required=False, 
            help='Analytic line linked if there\'s no invoice for this cost', 
            ondelete = 'set null',),
        'intervent_id': fields.many2one(
            'hr.analytic.timesheet.intervent', 'Intervent', 
            ondelete='cascade', required=False),
        'cost_unit': fields.float('Cost unit', digits=(16, 3)),
        'force_cost_unit': fields.float('Force cost unit', digits=(16, 3)),
        'locked': fields.boolean(
            'Locked', required=False, help='Locked when saved'),
        'direction_move': fields.selection([
            ('out', 'Move out'),
            ('in', 'Move in'),            
            ], 'Direction', select=True, readonly=False),
    }
    _defaults = {
        'locked': lambda *a: False,
        'account_id': lambda s, cr, uid, ctx: s.get_default_account_id(
            cr, uid, context=ctx),        
    }

class hr_analytic_timesheet(orm.Model):
    ''' Add relation field
    '''
    
    _inherit = 'hr.analytic.timesheet'
    
    # -----------------
    # Utility function:
    # -----------------
    def get_to_invoice(self, cr, uid, context=None):
        ''' Return default to_invoice value 
        '''
        cr.execute(
            """select res_id 
               from ir_model_data 
               where module = 'hr_analytic_intervent' 
                   and name = 'timesheet_invoice_factor_100';""")
        res = cr.fetchone()[0] or 0                         
        return res
    
    def get_sub_account(self, cr, uid, parent_account_id, partner_proxy, 
            economy=True, context=None):
        ''' Search or create a sub-account for ecomomy extra invoice intervent
        
            self: self object
            cr: database cursor 
            uid: user id
            parent_account_id: id of parent account
            partner_proxy: browse obj for get partner info
            economy: True if is an economy account, False for Contract account
            context: context dict
            @return: new account ID child of account_id for economy purpose            
        '''
        account_pool = self.pool.get('account.analytic.account')                         
        data = {
            'partner_id': partner_proxy.id,
            'type': 'normal',
            'parent_id': parent_account_id,
            'use_timesheets': True,
            'pricelist_id': 
                partner_proxy.property_product_pricelist \
                and partner_proxy.property_product_pricelist.id \
                or False,
        }
        domain = [('parent_id', '=', parent_account_id)]
        if economy:
            domain.append(('economy', '=', True))
            data['economy'] = True
            data['name'] = _("Economy")
        else:   
            domain.append(('contract', '=', True))
            data['contract'] = True
            data['name'] = _("Contract")
           
        item_ids = account_pool.search(cr, uid, domain, context=context)
        if item_ids:
            return item_ids[0]
            
        return account_pool.create(cr, uid, data, context=context)
    
    # -----------------
    # on change method:
    # -----------------
    def on_change_account_id_bis(self, cr, uid, ids, account_id, 
            #user_id, extra_invoice, 
            context=None):
        ''' Override function for problem setting to_invoice value (default 
            function reset the value)
        '''
        res = super(hr_analytic_timesheet, self).on_change_account_id(
            cr, uid, ids, account_id, user_id)
        if extra_invoice:
            if 'value' not in res:
                res['value'] = {}
            res['value']['to_invoice'] = self.get_to_invoice(
                cr, uid, context=context)
        return res
        
    def onchange_extra_invoice(self, cr, uid, ids, extra_invoice, 
            parent_partner_id, parent_account_id, account_id, context=None):
        ''' Setup to_invoice m2o field with extra_invoice boolean set up 
            default element created during installation of this module
        '''
        try:
            res = {'value': {'to_invoice': False}}
            if not parent_partner_id:
                res['value']['account_id'] = False # remove account
                return res # TODO raise
                
            partner_pool = self.pool.get('res.partner')
            partner_proxy = partner_pool.browse(
                cr, uid, parent_partner_id, context=context)
                
            if extra_invoice: # invoice and a new economy account set:
                res['value']['to_invoice'] = self.get_to_invoice(
                    cr, uid, context=context) 
                # TODO setted from onchange_account_id maybe remove from there
                
                res['value']['account_id'] = self.get_sub_account( # child economy
                    cr, uid, parent_account_id, partner_proxy, True, 
                    context=context)
            else:
                res['value']['account_id'] = self.get_sub_account(
                    cr, uid, parent_account_id, partner_proxy, False, # child contract 
                    context=context)
        except:
            raise osv.except_osv(
                _('Error:', 
                _('Not found default invoice factor, probably deleted (update all the database)')))
        return res

    # -----------------
    # Default function:
    # -----------------    
    def get_default_account_id(self, cr, uid, context=None):
        ''' Return default child contract account (or create)
        '''
        account_id = context.get('parent_account_id', False)
        if not account_id: 
            return False
            
        account_pool = self.pool.get('account.analytic.account')
        account_proxy = account_pool.browse(
            cr, uid, account_id, context=context)
        return self.get_sub_account(
            cr, uid, account_id, account_proxy.partner_id, False, 
            context=context)
        
    _columns = {
        'extra_invoice': fields.boolean('Extra invoice', 
            help='If extra invoice all the intervent are prepared for wizard invoice creation'),
        'intervent_id': fields.many2one(
            'hr.analytic.timesheet.intervent', 'Intervent', ondelete='cascade', 
            ),
    }
    _defaults = {
        'extra_invoice': lambda *x: False,
        'account_id': lambda s, cr, uid, ctx: s.get_default_account_id(
            cr, uid, context=ctx),
    }


class ProductTemplate(orm.Model):
    """ Add fields for manage economy works
    """    
    
    _inherit = 'product.template'
    
    _columns = {
        'is_transport': fields.boolean('Is Transport'),
        }
    

class account_analytic_line(orm.Model):
    """ Add fields for manage economy works
    """    
    
    _inherit = 'account.analytic.line'
    
    # ---------------
    # Onchange event:
    # ---------------
    def on_change_transport(self, cr, uid, ids, product_id, account_id, 
            unit_amount, context=None):
        ''' Set up all needed fields for create an analytic account
        '''        
        res = {}
        
        def get_journal_id(self, cr, uid, context=None):
            ''' Transport use a personal journal that is created here (bad!)
                if not exist
            '''
            journal_pool = self.pool.get('account.analytic.journal')
            journal_ids = journal_pool.search(cr, uid, [
                ('code', '=', 'TRANSP')], context=context)
            if journal_ids:
                return journal_ids[0]
            return journal_pool.create(cr, uid, {
                'name': 'Transport',
                'code': 'TRANSP',
                'type': 'general',
                'active': True,
                }, context=context)    
            
        if not product_id:
            return res
        if not account_id:
            _logger.error(
                'Account ID not present during onchange for transport')    
        journal_id = get_journal_id(self, cr, uid, context=context)

        product_pool = self.pool.get('product.product')
        product_proxy = product_pool.browse(
            cr, uid, product_id, context=context)

        account_pool = self.pool.get('account.analytic.account')
        account_proxy = account_pool.browse(
            cr, uid, account_id, context=context)

        # Search account child
        if not account_proxy.contract: # is a parent
            child_ids = account_pool.search(cr, uid, [
                ('parent_id', '=', account_id),
                ('contract', '=', True),
                ], context=context)        
            if child_ids:
                account_id = child_ids[0]
            else: # Error in child not present    
                _logger.error(
                    'Cannot find correct account (no child): %s' % account_id)
                res['warning'] = {
                    'title': 
                        _('Analytic account:'),
                    'message': 
                        _('Cannot assign child contract analytic account'),
                    }
                return res # Error account not well created

        # Add default data for creata an account.analytic.line            
        res['value'] = {
            'name': _('Transport: %s') % product_proxy.name,
            'ref': _('Trip: %s [%s]') % (
                product_proxy.default_code, 
                account_proxy.code,
                ),
            'general_account_id': 
                product_proxy.property_account_expense.id or \
                product_proxy.categ_id.property_account_expense_categ.id,
            'user_id': uid,
            'product_uom_id': product_proxy.uom_id.id,
            'amount': - product_proxy.standard_price * unit_amount,
            'account_id': account_id,
            'journal_id': journal_id,
            #'to_invoice' 'unit_amount_price' 'unit_price'
            }                    
        return res

    # ----------------- 
    # Utility function:
    # ----------------- 
    def _get_hr_timesheet(self, cr, uid, ids, name, args, context=None):
        ''' Search relative intervent in work journal
        '''
        res = dict.fromkeys(ids, False)
        try:
            cr.execute("""
                SELECT line_id, intervent_id 
                FROM hr_analytic_timesheet 
                WHERE line_id in (%s)""" % tuple(ids))
            for item in cr.fetchall():
                res[item[0]] = item[1]
        except:
            pass # return nothing
        return res
        
    def _get_unit_amount_price(self, cr, uid, ids, name, args, context=None):
        ''' Calculate price
        '''
        res = {}
        try:
            for move in self.browse(cr, uid, ids, context=context):
                res[move.id] = abs(
                    move.amount / move.unit_amount if move.unit_amount else 0.0)
        except:
            pass # return nothing
        return res

    _columns = {
        'timesheet_transport_id': fields.many2one(
            'hr.analytic.timesheet.intervent', string='Timesheet transport',
            ondelete='cascade'),
        'partner_id': fields.related('account_id','partner_id',
            type='many2one', relation='res.partner', string='Partner', 
            store=True),
        'work_journal_intervent_id': fields.many2one(
            'hr.analytic.timesheet.intervent', 'Work journal row', 
            required=False),
        'work_journal_timesheet_id': fields.function(_get_hr_timesheet, 
            method=True, type='many2one', 
            relation='hr.analytic.timesheet.intervent', 
            string='Work journal row', store=False),
        'unit_amount_price': fields.function(_get_unit_amount_price, 
            method=True, type='float', 
            string='Unit price', 
            store=False),        
        }

class hr_analytic_timesheet_intervent(orm.Model):
    ''' Add *2many fields
    '''
    
    _inherit = 'hr.analytic.timesheet.intervent'

    _columns = {
        'move_ids': fields.one2many(
            'stock.move', 'intervent_id', 'Costs', 
            required=False),
        'employee_ids': fields.one2many(
            'hr.analytic.timesheet', 
            'intervent_id', 'Employee', required=False),
        'transport_ids': fields.one2many(
            'account.analytic.line', 'timesheet_transport_id', 
            'Transport'),
        }
    
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
