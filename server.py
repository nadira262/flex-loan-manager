"""
SFS Credit Review Tool — Backend Server
Queries Snowflake for real loan application data.
Run: python3 server.py
Then open: http://localhost:5050/sfs-credit-review.html
"""

import json
import os
import sys
from datetime import datetime, date
from flask import Flask, request, jsonify, send_from_directory
import snowflake.connector

app = Flask(__name__, static_folder='.')

# Snowflake connection config
SF_CONFIG = {
    'account': 'square',
    'user': os.environ.get('SNOWFLAKE_USER', 'nadira@squareup.com'),
    'authenticator': 'externalbrowser',
    'warehouse': 'ADHOC__LARGE',
}

_conn = None

def get_conn():
    global _conn
    if _conn is None or _conn.is_closed():
        _conn = snowflake.connector.connect(**{k:v for k,v in SF_CONFIG.items() if v})
    return _conn

def query(sql, params=None):
    conn = get_conn()
    cur = conn.cursor(snowflake.connector.DictCursor)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
        # Convert dates/datetimes to strings
        result = []
        for row in rows:
            clean = {}
            for k, v in row.items():
                if isinstance(v, (datetime, date)):
                    clean[k] = v.isoformat()
                else:
                    clean[k] = v
            result.append(clean)
        return result
    finally:
        cur.close()

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)

@app.route('/')
def index():
    return send_from_directory('.', 'sfs-credit-review-live.html')

@app.route('/api/application', methods=['GET'])
def get_application():
    token = request.args.get('token', '').strip()
    if not token:
        return jsonify({'error': 'No application token provided'}), 400

    try:
        # 1. Get application details and blockers
        app_data = query("""
            SELECT 
                APPLICATION_TOKEN,
                APPLICATION_SUBMITTED_AT,
                APPLICATION_STATUS,
                PRODUCT_NAME,
                PRODUCT_ID,
                AUTO_STEP_TYPE,
                AUTO_STEP_STATUS,
                AUTO_STEP_RESULT,
                AUTO_STEP_FAILURE_REASON,
                MANUAL_STEP_TYPE,
                MANUAL_STEP_STATUS,
                MANUAL_STEP_RESULT,
                UNIT_TOKEN,
                COUNTRY_CODE,
                RISK_GRADE_NAME,
                MERCHANT_BUSINESS_CATEGORY,
                SELECTED_OFFER_RECEIVABLE_AMOUNT,
                SELECTED_OFFER_AMOUNT,
                MERCHANT_GPV_SEGMENT,
                AGGREGATED_AUTO_STEP_FAILURE_REASON,
                CASE_HAS_SSP,
                SSP_STATE,
                SSP_CREATED_AT,
                RISK_SLA,
                COMPLIANCE_SLA,
                APPLICATION_SLA,
                OFFER_TYPE,
                QUEUE_NAME,
                CASE_CLOSED_AT,
                INCOMPLETE_STEP
            FROM APP_CAPITAL.APP_CAPITAL.LOAN_APPLICATION_STEPS
            WHERE APPLICATION_TOKEN = %s
            ORDER BY AUTO_STEP_CREATED_AT DESC
        """, (token,))

        if not app_data:
            return jsonify({'error': f'Application {token} not found'}), 404

        unit_token = app_data[0].get('UNIT_TOKEN')
        if not unit_token:
            return jsonify({'error': 'No unit token found for this application'}), 404

        # 2. Get merchant details
        merchant = query("""
            SELECT 
                BEST_AVAILABLE_UNIT_TOKEN AS UNIT_TOKEN,
                MERCHANT_TOKEN,
                BUSINESS_NAME,
                BUSINESS_TYPE,
                BUSINESS_CATEGORY,
                RECEIPT_STATE,
                RECEIPT_CITY,
                RECEIPT_COUNTRY_CODE,
                USER_CREATED_AT_DATE,
                UNIT_ACTIVE_STATUS,
                IS_CURRENTLY_FROZEN,
                IS_CURRENTLY_DEACTIVATED,
                AUDIENCE_PREDICTED,
                SUB_AUDIENCE_PREDICTED
            FROM APP_BI.HEXAGON.VDIM_USER
            WHERE BEST_AVAILABLE_UNIT_TOKEN = %s
              AND IS_UNIT = 1
        """, (unit_token,))

        # 3. Get active loans for this merchant
        merchant_token = merchant[0].get('MERCHANT_TOKEN') if merchant else None
        loans = []
        if merchant_token:
            loans = query("""
                SELECT 
                    pg.PLAN_GROUP_ID,
                    pg.PRODUCT_NAME,
                    pg.PRODUCT_ID,
                    pg.STATUS,
                    pg.FINANCED_CENTS,
                    pg.FEE_CENTS,
                    pg.RECEIVABLES_CENTS,
                    pg.HOLD_RATE_BPS,
                    pg.RISK_GRADE_NAME,
                    pg.ACTIVATED_AT,
                    pg.CLOSED_AT,
                    pg.ORIGINATION_TYPE,
                    pg.PRIOR_PLAN_GROUP_COUNT,
                    pg.CURRENCY_CODE
                FROM APP_CAPITAL.APP_CAPITAL.PLAN_GROUPS pg
                WHERE pg.PRIMARY_USER_TOKEN = %s
                  AND pg.STATUS NOT IN ('canceled', 'declined')
                ORDER BY pg.ACTIVATED_AT DESC
            """, (merchant_token,))

        # 4. Get offer details
        offer_set_id = app_data[0].get('OFFER_SET_ID')
        offer = []
        if not offer_set_id:
            # Try to get from offer_sets using unit token
            offer = query("""
                SELECT 
                    OFFER_SET_ID,
                    FINANCED_AMOUNT_CENTS,
                    FEE_RATE_BPS,
                    OFFER_HOLD_RATE_BPS,
                    RISK_GRADE_NAME,
                    OFFER_CREATED_AT,
                    PRODUCT_ID,
                    WAS_ACCEPTED,
                    PLAN_ACTIVATED,
                    PLAN_HOLD_RATE_BPS,
                    OFFER_TYPE
                FROM APP_CAPITAL.APP_CAPITAL.OFFER_SETS
                WHERE MERCHANT_TOKEN = %s
                  AND WAS_ACCEPTED = 1
                  AND PLAN_ACTIVATED IS NOT NULL
                ORDER BY OFFER_CREATED_AT DESC
                LIMIT 5
            """, (merchant_token,))

        # 5. Get GPV data (last 180 days)
        gpv = query("""
            SELECT 
                PAYMENT_TRX_RECOGNIZED_DATE AS THE_DATE,
                TOTAL_PAYMENT_COUNT,
                GPV_PAYMENT_AMOUNT_BASE_UNIT,
                GPV_PAYMENT_COUNT,
                CP_CARD_PAYMENT_COUNT,
                CNP_CARD_PAYMENT_COUNT,
                CP_CARD_PAYMENT_AMOUNT_BASE_UNIT,
                CNP_CARD_PAYMENT_AMOUNT_BASE_UNIT,
                UNIQUE_PAYMENT_CARDS
            FROM APP_BI.HEXAGON_TABLE.AGGREGATE_SELLER_DAILY_PAYMENT_SUMMARY_BASE
            WHERE UNIT_TOKEN = %s
              AND CURRENCY_CODE = 'USD'
              AND PAYMENT_TRX_RECOGNIZED_DATE >= DATEADD('day', -180, CURRENT_DATE())
            ORDER BY PAYMENT_TRX_RECOGNIZED_DATE DESC
        """, (unit_token,))

        # 6. Get disputes/chargebacks (last 12 months)
        disputes = query("""
            SELECT 
                CHARGEBACK_ID,
                PAYMENT_TOKEN,
                DISPUTED_AMOUNT,
                PAYMENT_AMOUNT,
                REPORTING_DATE,
                DISPUTE_TYPE,
                REASON_CODE,
                REASON_CODE_CATEGORY,
                REASON_CODE_TYPE,
                CARD_BRAND,
                ENTRY_METHOD,
                CURRENT_RESOLUTION,
                SELLER_ACTION,
                SQUARE_ACTION,
                LOSS_CENTS,
                IS_MOST_RECENT
            FROM APP_RISK.APP_RISK.DISPUTES
            WHERE UNIT_TOKEN = %s
              AND REPORTING_DATE >= DATEADD('month', -12, CURRENT_DATE())
            ORDER BY REPORTING_DATE DESC
        """, (unit_token,))

        # 7. Get linked accounts with active loans
        linked = []
        if merchant_token:
            linked = query("""
                WITH merchant_units AS (
                    SELECT DISTINCT BEST_AVAILABLE_UNIT_TOKEN AS UT, BUSINESS_NAME
                    FROM APP_BI.HEXAGON.VDIM_USER
                    WHERE MERCHANT_TOKEN = %s AND IS_UNIT = 1
                )
                SELECT 
                    mu.UT AS LINKED_UNIT_TOKEN,
                    mu.BUSINESS_NAME AS LINKED_BUSINESS_NAME,
                    pg.PLAN_GROUP_ID,
                    pg.PRODUCT_NAME,
                    pg.STATUS,
                    pg.FINANCED_CENTS,
                    pg.RISK_GRADE_NAME,
                    pg.ACTIVATED_AT
                FROM merchant_units mu
                JOIN APP_CAPITAL.APP_CAPITAL.PLAN_GROUPS pg 
                    ON pg.PRIMARY_USER_TOKEN = mu.UT
                WHERE pg.STATUS IN ('allocated', 'originated', 'approved')
                  AND mu.UT != %s
                ORDER BY pg.ACTIVATED_AT DESC
            """, (merchant_token, unit_token))

        # 8. Get repayment data for active loans
        active_plan_ids = [l['PLAN_GROUP_ID'] for l in loans if l.get('STATUS') in ('allocated', 'originated', 'approved')]
        repayment = []
        if active_plan_ids:
            placeholders = ','.join(['%s'] * len(active_plan_ids))
            repayment = query(f"""
                SELECT 
                    PLAN_GROUP_ID,
                    THE_DATE,
                    DAYS_SINCE_ACTIVATION,
                    CUMULATIVE_REPAYMENT_CENTS,
                    CUMULATIVE_OUTSTANDING_CENTS,
                    CUMULATIVE_REPAYMENT_FRACTION,
                    RECEIVABLES_CENTS,
                    ESTIMATED_OVERALL_DURATION_DAYS
                FROM APP_CAPITAL.APP_CAPITAL.PLAN_GROUP_DAILY_CUMULATIVE_REPAYMENT
                WHERE PLAN_GROUP_ID IN ({placeholders})
                  AND THE_DATE = (SELECT MAX(THE_DATE) FROM APP_CAPITAL.APP_CAPITAL.PLAN_GROUP_DAILY_CUMULATIVE_REPAYMENT)
            """, tuple(str(pid) for pid in active_plan_ids))

        return jsonify({
            'application': app_data,
            'merchant': merchant[0] if merchant else None,
            'loans': loans,
            'offer': offer,
            'gpv': gpv,
            'disputes': disputes,
            'linked_accounts': linked,
            'repayment': repayment
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/unit', methods=['GET'])
def get_unit():
    """Look up by unit token instead of application token"""
    token = request.args.get('token', '').strip()
    if not token:
        return jsonify({'error': 'No unit token provided'}), 400

    try:
        # Get merchant details
        merchant = query("""
            SELECT 
                BEST_AVAILABLE_UNIT_TOKEN AS UNIT_TOKEN,
                MERCHANT_TOKEN,
                BUSINESS_NAME,
                BUSINESS_TYPE,
                BUSINESS_CATEGORY,
                RECEIPT_STATE,
                RECEIPT_CITY,
                RECEIPT_COUNTRY_CODE,
                USER_CREATED_AT_DATE,
                UNIT_ACTIVE_STATUS,
                IS_CURRENTLY_FROZEN,
                IS_CURRENTLY_DEACTIVATED,
                AUDIENCE_PREDICTED,
                SUB_AUDIENCE_PREDICTED
            FROM APP_BI.HEXAGON.VDIM_USER
            WHERE BEST_AVAILABLE_UNIT_TOKEN = %s
              AND IS_UNIT = 1
        """, (token,))

        if not merchant:
            return jsonify({'error': f'Unit token {token} not found'}), 404

        # Get pending applications
        apps = query("""
            SELECT DISTINCT
                APPLICATION_TOKEN,
                APPLICATION_SUBMITTED_AT,
                APPLICATION_STATUS,
                PRODUCT_NAME,
                SELECTED_OFFER_AMOUNT,
                SELECTED_OFFER_RECEIVABLE_AMOUNT,
                RISK_GRADE_NAME,
                AGGREGATED_AUTO_STEP_FAILURE_REASON
            FROM APP_CAPITAL.APP_CAPITAL.LOAN_APPLICATION_STEPS
            WHERE UNIT_TOKEN = %s
              AND APPLICATION_STATUS = 'submitted'
            ORDER BY APPLICATION_SUBMITTED_AT DESC
        """, (token,))

        return jsonify({
            'merchant': merchant[0],
            'pending_applications': apps
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("\n" + "="*60)
    print("  SFS Credit Review Tool — Server")
    print("="*60)
    print("\n  Starting server...")
    print("  Open: http://localhost:5050")
    print("  Press Ctrl+C to stop\n")
    app.run(host='0.0.0.0', port=5050, debug=True)
