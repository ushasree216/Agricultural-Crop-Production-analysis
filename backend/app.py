from flask import Flask, jsonify, request, send_file
import config
import mysql.connector
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from io import BytesIO

app = Flask(__name__)


def fetch_all(sql, params=()):
    db = config.connect()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def fetch_one(sql, params=()):
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute_query(sql, params=()):
    db = config.connect()
    cursor = db.cursor()
    try:
        cursor.execute(sql, params)
        db.commit()
        return cursor.lastrowid, cursor.rowcount
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def error_response(message, status=400):
    return jsonify({"error": message}), status


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Agricultural Crop Production Analysis API",
        "status": "running"
    })


@app.route("/crops", methods=["GET"])
def get_crops():
    return jsonify(fetch_all(
        "SELECT * FROM crops ORDER BY crop_name"
    ))


@app.route("/crops", methods=["POST"])
def add_crop():
    data = request.get_json(silent=True) or {}
    crop_name = data.get("crop_name")

    if not crop_name or not str(crop_name).strip():
        return error_response("crop_name is required")

    try:
        crop_id, _ = execute_query(
            "INSERT INTO crops (crop_name) VALUES (%s)",
            (str(crop_name).strip(),)
        )
        return jsonify({
            "message": "Crop added successfully",
            "crop_id": crop_id
        }), 201
    except mysql.connector.Error as exc:
        return error_response(str(exc), 400)


@app.route("/regions", methods=["GET"])
def get_regions():
    return jsonify(fetch_all(
        "SELECT * FROM regions ORDER BY region_name"
    ))


@app.route("/regions", methods=["POST"])
def add_region():
    data = request.get_json(silent=True) or {}
    region_name = data.get("region_name")

    if not region_name or not str(region_name).strip():
        return error_response("region_name is required")

    try:
        region_id, _ = execute_query(
            "INSERT INTO regions (region_name) VALUES (%s)",
            (str(region_name).strip(),)
        )
        return jsonify({
            "message": "Region added successfully",
            "region_id": region_id
        }), 201
    except mysql.connector.Error as exc:
        return error_response(str(exc), 400)


@app.route("/records", methods=["GET"])
def get_records():
    records = fetch_all("""
        SELECT cr.record_id, cr.crop_id, c.crop_name,
               cr.region_id, r.region_name, cr.year,
               cr.cultivated_area, cr.area_unit,
               cr.production, cr.production_unit,
               cr.rainfall, cr.rainfall_unit
        FROM crop_records cr
        JOIN crops c ON cr.crop_id = c.crop_id
        JOIN regions r ON cr.region_id = r.region_id
        ORDER BY cr.year, c.crop_name, r.region_name
    """)
    return jsonify(records)


@app.route("/records/<int:record_id>", methods=["GET"])
def get_record(record_id):
    record = fetch_one("""
        SELECT cr.record_id, cr.crop_id, c.crop_name,
               cr.region_id, r.region_name, cr.year,
               cr.cultivated_area, cr.area_unit,
               cr.production, cr.production_unit,
               cr.rainfall, cr.rainfall_unit
        FROM crop_records cr
        JOIN crops c ON cr.crop_id = c.crop_id
        JOIN regions r ON cr.region_id = r.region_id
        WHERE cr.record_id = %s
    """, (record_id,))

    if not record:
        return error_response("Crop record not found", 404)

    return jsonify(record)


@app.route("/records", methods=["POST"])
def add_record():
    data = request.get_json(silent=True) or {}

    required = [
        "crop_id", "region_id", "year", "cultivated_area",
        "area_unit", "production", "production_unit"
    ]

    missing = [
        field for field in required
        if data.get(field) is None
    ]

    if missing:
        return error_response(
            "Missing required fields: " + ", ".join(missing)
        )

    try:
        crop_id = int(data["crop_id"])
        region_id = int(data["region_id"])
        year = int(data["year"])
        area = float(data["cultivated_area"])
        production = float(data["production"])
        rainfall = data.get("rainfall")

        if year < 1900 or year > 2100:
            return error_response(
                "year must be between 1900 and 2100"
            )

        if area <= 0:
            return error_response(
                "cultivated_area must be greater than zero"
            )

        if production < 0:
            return error_response(
                "production cannot be negative"
            )

        if rainfall is not None and float(rainfall) < 0:
            return error_response(
                "rainfall cannot be negative"
            )

        record_id, _ = execute_query("""
            INSERT INTO crop_records
            (crop_id, region_id, year, cultivated_area, area_unit,
             production, production_unit, rainfall, rainfall_unit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            crop_id,
            region_id,
            year,
            area,
            data["area_unit"],
            production,
            data["production_unit"],
            rainfall,
            data.get(
                "rainfall_unit",
                "mm" if rainfall is not None else None
            )
        ))

        return jsonify({
            "message": "Crop record added successfully",
            "record_id": record_id
        }), 201

    except (ValueError, TypeError):
        return error_response(
            "IDs, year, area, production and rainfall must be valid numbers"
        )
    except mysql.connector.Error as exc:
        return error_response(str(exc), 400)


@app.route("/records/<int:record_id>", methods=["PUT"])
def update_record(record_id):
    data = request.get_json(silent=True) or {}

    allowed = {
        "crop_id", "region_id", "year", "cultivated_area",
        "area_unit", "production", "production_unit",
        "rainfall", "rainfall_unit"
    }

    updates = {
        key: value
        for key, value in data.items()
        if key in allowed
    }

    if not updates:
        return error_response(
            "Provide at least one valid field to update"
        )

    if not fetch_one(
        "SELECT record_id FROM crop_records WHERE record_id = %s",
        (record_id,)
    ):
        return error_response("Crop record not found", 404)

    try:
        for field in ("crop_id", "region_id", "year"):
            if field in updates:
                updates[field] = int(updates[field])

        for field in (
            "cultivated_area", "production", "rainfall"
        ):
            if field in updates and updates[field] is not None:
                updates[field] = float(updates[field])

        if (
            "cultivated_area" in updates
            and updates["cultivated_area"] <= 0
        ):
            return error_response(
                "cultivated_area must be greater than zero"
            )

        if (
            "production" in updates
            and updates["production"] < 0
        ):
            return error_response(
                "production cannot be negative"
            )

        if (
            "rainfall" in updates
            and updates["rainfall"] is not None
            and updates["rainfall"] < 0
        ):
            return error_response(
                "rainfall cannot be negative"
            )

        columns = ", ".join(
            f"{column} = %s" for column in updates
        )

        execute_query(
            f"UPDATE crop_records SET {columns} WHERE record_id = %s",
            list(updates.values()) + [record_id]
        )

        return jsonify({
            "message": "Crop record updated successfully"
        })

    except (ValueError, TypeError):
        return error_response(
            "Numeric fields must contain valid numbers"
        )
    except mysql.connector.Error as exc:
        return error_response(str(exc), 400)


@app.route("/records/<int:record_id>", methods=["DELETE"])
def delete_record(record_id):
    try:
        _, affected = execute_query(
            "DELETE FROM crop_records WHERE record_id = %s",
            (record_id,)
        )

        if affected == 0:
            return error_response("Crop record not found", 404)

        return jsonify({
            "message": "Crop record deleted successfully"
        })

    except mysql.connector.Error as exc:
        return error_response(str(exc), 400)


@app.route("/reports/summary", methods=["GET"])
def production_summary():
    result = fetch_one("""
        SELECT COUNT(*) AS total_records,
               COUNT(DISTINCT crop_id) AS total_crops,
               COUNT(DISTINCT region_id) AS total_regions,
               MIN(year) AS first_year,
               MAX(year) AS last_year,
               COALESCE(SUM(production), 0) AS total_production
        FROM crop_records
    """)

    return jsonify(result)


@app.route("/analytics/yield", methods=["GET"])
def yield_analysis():
    rows = fetch_all("""
        SELECT c.crop_name, r.region_name, cr.year,
               cr.cultivated_area, cr.area_unit,
               cr.production, cr.production_unit,
               CASE
                   WHEN cr.cultivated_area > 0
                   THEN cr.production / cr.cultivated_area
                   ELSE NULL
               END AS yield_value
        FROM crop_records cr
        JOIN crops c ON cr.crop_id = c.crop_id
        JOIN regions r ON cr.region_id = r.region_id
        ORDER BY cr.year, c.crop_name, r.region_name
    """)

    return jsonify(rows)


@app.route("/analytics/year-comparison", methods=["GET"])
def year_comparison():
    crop_id = request.args.get("crop_id")
    region_id = request.args.get("region_id")

    sql = """
        SELECT cr.year, c.crop_name, r.region_name,
               cr.cultivated_area, cr.area_unit,
               cr.production, cr.production_unit,
               cr.rainfall, cr.rainfall_unit
        FROM crop_records cr
        JOIN crops c ON cr.crop_id = c.crop_id
        JOIN regions r ON cr.region_id = r.region_id
        WHERE 1 = 1
    """

    params = []

    if crop_id:
        sql += " AND cr.crop_id = %s"
        params.append(crop_id)

    if region_id:
        sql += " AND cr.region_id = %s"
        params.append(region_id)

    sql += " ORDER BY cr.year"

    return jsonify(fetch_all(sql, tuple(params)))


@app.route("/analytics/production-by-crop", methods=["GET"])
def production_by_crop():
    rows = fetch_all("""
        SELECT c.crop_name, cr.production_unit,
               SUM(cr.production) AS total_production
        FROM crop_records cr
        JOIN crops c ON cr.crop_id = c.crop_id
        GROUP BY c.crop_name, cr.production_unit
        ORDER BY total_production DESC
    """)

    return jsonify(rows)


@app.route("/analytics/production-pandas", methods=["GET"])
def production_pandas():
    rows = fetch_all("""
        SELECT c.crop_name, r.region_name, cr.year,
               cr.production, cr.production_unit
        FROM crop_records cr
        JOIN crops c ON cr.crop_id = c.crop_id
        JOIN regions r ON cr.region_id = r.region_id
    """)

    if not rows:
        return jsonify([])

    df = pd.DataFrame(rows)

    summary = (
        df.groupby(
            ["crop_name", "region_name", "year", "production_unit"],
            as_index=False
        )["production"].sum()
    )

    return jsonify(summary.to_dict(orient="records"))


@app.route("/analytics/production-numpy", methods=["GET"])
def production_numpy():
    rows = fetch_all("""
        SELECT c.crop_name, cr.year,
               cr.production, cr.production_unit
        FROM crop_records cr
        JOIN crops c ON cr.crop_id = c.crop_id
        ORDER BY cr.year, c.crop_name
    """)

    if not rows:
        return jsonify({
            "records": [],
            "average_production": 0
        })

    values = np.array(
        [float(row["production"] or 0) for row in rows],
        dtype=float
    )

    result = []

    for index, row in enumerate(rows):
        result.append({
            "crop_name": row["crop_name"],
            "year": row["year"],
            "production": float(values[index]),
            "production_unit": row["production_unit"]
        })

    return jsonify({
        "records": result,
        "average_production": round(float(np.mean(values)), 2),
        "total_production": round(float(np.sum(values)), 2)
    })


def chart_response():
    image_buffer = BytesIO()
    plt.tight_layout()
    plt.savefig(
        image_buffer,
        format="png",
        bbox_inches="tight"
    )
    image_buffer.seek(0)
    plt.close()

    return send_file(
        image_buffer,
        mimetype="image/png"
    )


@app.route("/charts/production-by-crop", methods=["GET"])
def production_by_crop_chart():
    rows = fetch_all("""
        SELECT c.crop_name, cr.production_unit,
               SUM(cr.production) AS total_production
        FROM crop_records cr
        JOIN crops c ON cr.crop_id = c.crop_id
        GROUP BY c.crop_name, cr.production_unit
        ORDER BY total_production 
    """)

    if not rows:
        return error_response(
            "No crop production data available", 404
        )

    names = [row["crop_name"] for row in rows]
    values = [
        float(row["total_production"] or 0)
        for row in rows
    ]

    plt.figure(figsize=(11, 6))
    plt.bar(names, values)
    plt.title("Total Production by Crop")
    plt.xlabel("Crop")
    plt.ylabel("Total Production (grouped by stored units)")
    plt.xticks(rotation=45, ha="right")

    return chart_response()


@app.route("/charts/yearly-production", methods=["GET"])
def yearly_production_chart():
    rows = fetch_all("""
        SELECT year, production_unit,
               SUM(production) AS total_production
        FROM crop_records
        GROUP BY year, production_unit
        ORDER BY year
    """)

    if not rows:
        return error_response(
            "No crop production data available", 404
        )

    labels = [
        f'{row["year"]} ({row["production_unit"]})'
        for row in rows
    ]

    values = [
        float(row["total_production"] or 0)
        for row in rows
    ]

    plt.figure(figsize=(10, 5))
    plt.plot(labels, values, marker="o")
    plt.title("Yearly Crop Production")
    plt.xlabel("Year and production unit")
    plt.ylabel("Total Production")
    plt.xticks(rotation=45, ha="right")

    return chart_response()


if __name__ == "__main__":
    app.run(debug=True)