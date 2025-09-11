import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function UserScreen({ route }) {
    const { user } = route.params;

    return (
        <View style={styles.container}>
            <Text style={styles.title}>User Details</Text>
            <View style={styles.detailCard}>
                <Text style={styles.label}>ID:</Text>
                <Text style={styles.value}>{user.id}</Text>
            </View>
            <View style={styles.detailCard}>
                <Text style={styles.label}>Name:</Text>
                <Text style={styles.value}>{user.name}</Text>
            </View>
            <View style={styles.detailCard}>
                <Text style={styles.label}>Email:</Text>
                <Text style={styles.value}>{user.email}</Text>
            </View>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        padding: 20,
        backgroundColor: '#f5f5f5',
    },
    title: {
        fontSize: 24,
        fontWeight: 'bold',
        marginBottom: 20,
    },
    detailCard: {
        flexDirection: 'row',
        backgroundColor: 'white',
        padding: 15,
        marginVertical: 5,
        borderRadius: 8,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.2,
        shadowRadius: 1,
        elevation: 2,
    },
    label: {
        fontSize: 16,
        fontWeight: 'bold',
        marginRight: 10,
        minWidth: 60,
    },
    value: {
        fontSize: 16,
        flex: 1,
    },
});