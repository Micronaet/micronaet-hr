# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>). All Rights Reserved
#    $Id$
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

{
    'name': 'HR analytic intervent',
    'version': '0.0.1',
    'category': 'Analytic/Intervent',
    
    'description': """Create a new object: intervent
that is the parent from analytic line (work of every
employee in a contract) and material that is used for
that intervent (materials are only unloaded, no invoice
and costs of employee are linked to contract)
    """,
    
    'author': 'Micronaet s.r.l.',
    'website': 'http://www.micronaet.it',
    'depends': [
        'base',
        'account',
        'analytic',
        'account_analytic_analysis',
        'hr_timesheet',
        'hr_timesheet_invoice',
        'hr_attendance',          
    ],
    'init_xml': [], 
    'data': [
        'security/ir.model.access.csv',
        'intervent_view.xml',
        #'intervent_workflow.xml',
        'report/registry_report.xml',
        'wizard/work_report_view.xml',

        'data/hr_timesheet_invoice_data.xml',
    ],
    'demo_xml': [],
    'active': False, 
    'installable': True, 
}
