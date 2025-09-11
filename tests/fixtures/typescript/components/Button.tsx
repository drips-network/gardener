// A simple React component (TSX)

import React, { Component } from 'react'; // Named import from React
import type { MouseEvent } from 'react'; // Type-only import from React

interface ButtonProps {
    label: string;
    onClick: (event: MouseEvent<HTMLButtonElement>) => void;
    // Using a path alias for types
    theme?: import('@utils/index').UtilityUser; // This is a bit contrived for testing path alias
}

class Button extends Component<ButtonProps> {
    // Import inside a class (less common, but possible for dynamic scenarios)
    async dynamicImport() {
        const _ = await import('lodash');
        console.log('Lodash loaded dynamically in Button component:', _.VERSION);
    }

    render() {
        // Example of using an import within a method
        const { joinPath } = require('../utils/helpers'); // CommonJS style import for testing
        const buttonId = joinPath('button', this.props.label.toLowerCase());

        return (
            <button id={buttonId} onClick={this.props.onClick}>
                {this.props.label}
            </button>
        );
    }
}

export default Button;