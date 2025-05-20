def resolve_subrecipe_ingredients_detailed(conn, sub_recipe_id, final_qty=None, path=""):
    def get_total_cost_and_weight(sub_id):
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sri.quantity, i.price_per_unit
            FROM sub_recipe_ingredients sri
            JOIN ingredients i ON sri.ingredient_id = i.id
            WHERE sri.sub_recipe_id = %s
        ''', (sub_id,))
        direct_items = cursor.fetchall()
        direct_cost = sum(float(q) * float(p) for q, p in direct_items)
        direct_weight = sum(float(q) for q, _ in direct_items)

        cursor.execute('SELECT sub_recipe_id, quantity FROM sub_recipe_nested WHERE parent_sub_recipe_id = %s', (sub_id,))
        nested_items = cursor.fetchall()
        nested_cost = 0
        nested_weight = 0

        for nested_sub_id, qty in nested_items:
            nc, nw = get_total_cost_and_weight(nested_sub_id)
            if nw > 0:
                nested_cost += (nc / nw) * float(qty)
                nested_weight += float(qty)

        return direct_cost + nested_cost, direct_weight + nested_weight

    def flatten_nested_subrecipe(nested_id, nested_qty, current_path, parent_qty=1.0, parent_total=1.0):
        flat_result = []
        cursor = conn.cursor()
        total_cost, total_weight = get_total_cost_and_weight(nested_id)
        if total_weight == 0:
            return flat_result

        cursor.execute('''
            SELECT sri.ingredient_id, sri.quantity, i.name, i.unit, i.price_per_unit
            FROM sub_recipe_ingredients sri
            JOIN ingredients i ON sri.ingredient_id = i.id
            WHERE sri.sub_recipe_id = %s
        ''', (nested_id,))
        for ing_id, qty, name, unit, price in cursor.fetchall():
            scaled_qty = float(qty) / total_weight * float(nested_qty) / parent_total * parent_qty
            flat_result.append({
                'source': current_path,
                'ingredient': name,
                'unit': unit,
                'quantity': scaled_qty,
                'cost': scaled_qty * float(price)
            })

        cursor.execute('SELECT sub_recipe_id, quantity FROM sub_recipe_nested WHERE parent_sub_recipe_id = %s', (nested_id,))
        for inner_id, inner_qty in cursor.fetchall():
            flat_result.extend(flatten_nested_subrecipe(inner_id, inner_qty, current_path, parent_qty=nested_qty, parent_total=total_weight))

        return flat_result

    cursor = conn.cursor()
    result = []

    cursor.execute('SELECT name FROM sub_recipes WHERE id = %s', (sub_recipe_id,))
    sub_name_row = cursor.fetchone()
    if not sub_name_row:
        return []

    sub_name = sub_name_row[0]
    current_path = f"{path} → {sub_name}" if path else sub_name

    total_cost, total_weight = get_total_cost_and_weight(sub_recipe_id)
    if total_weight == 0:
        return []

    if final_qty is None:
        final_qty = total_weight

    cursor.execute('''
        SELECT sri.ingredient_id, sri.quantity, i.name, i.unit, i.price_per_unit
        FROM sub_recipe_ingredients sri
        JOIN ingredients i ON sri.ingredient_id = i.id
        WHERE sri.sub_recipe_id = %s
    ''', (sub_recipe_id,))
    for ing_id, qty, name, unit, price in cursor.fetchall():
        proportion = float(qty) / total_weight
        scaled_qty = proportion * final_qty
        result.append({
            'source': current_path,
            'ingredient': name,
            'unit': unit,
            'quantity': scaled_qty,
            'cost': scaled_qty * float(price)
        })

    cursor.execute('SELECT sub_recipe_id, quantity FROM sub_recipe_nested WHERE parent_sub_recipe_id = %s', (sub_recipe_id,))
    for nested_id, nested_qty in cursor.fetchall():
        result.extend(flatten_nested_subrecipe(nested_id, nested_qty, current_path, parent_qty=final_qty, parent_total=total_weight))

    return result
